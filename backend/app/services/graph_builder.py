"""
图谱构建服务
接口2：使用GraphitiClient构建Standalone Graph
"""

import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from .graph_client import GraphitiClient

from ..models.task import TaskManager, TaskStatus
from ..utils.neo4j_paging import get_all_nodes_paginated, get_all_edges_paginated
from .text_processor import TextProcessor


@dataclass
class GraphInfo:
    """图谱信息"""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


class GraphBuilderService:
    """
    图谱构建服务
    负责调用GraphitiClient构建知识图谱
    """

    def __init__(self):
        self.client = GraphitiClient()
        self.task_manager = TaskManager()
    
    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "MiroFish Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3
    ) -> str:
        """
        异步构建图谱
        
        Args:
            text: 输入文本
            ontology: 本体定义（来自接口1的输出）
            graph_name: 图谱名称
            chunk_size: 文本块大小
            chunk_overlap: 块重叠大小
            batch_size: 每批发送的块数量
            
        Returns:
            任务ID
        """
        # 创建任务
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            }
        )
        
        # 在后台线程中执行构建
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap, batch_size)
        )
        thread.daemon = True
        thread.start()
        
        return task_id
    
    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int
    ):
        """图谱构建工作线程"""
        try:
            self.task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message="开始构建图谱..."
            )
            
            # 1. 创建图谱
            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(
                task_id,
                progress=10,
                message=f"图谱已创建: {graph_id}"
            )
            
            # 2. 设置本体
            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(
                task_id,
                progress=15,
                message="本体已设置"
            )
            
            # 3. 文本分块
            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(
                task_id,
                progress=20,
                message=f"文本已分割为 {total_chunks} 个块"
            )
            
            # 4. 分批发送数据 (Graphiti processes synchronously, no polling needed)
            episode_uuids = self.add_text_batches(
                graph_id, chunks, batch_size,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 0.7),  # 20-90%
                    message=msg
                )
            )

            # 5. 获取图谱信息
            self.task_manager.update_task(
                task_id,
                progress=90,
                message="获取图谱信息..."
            )
            
            graph_info = self._get_graph_info(graph_id)
            
            # 完成
            self.task_manager.complete_task(task_id, {
                "graph_id": graph_id,
                "graph_info": graph_info.to_dict(),
                "chunks_processed": total_chunks,
            })
            
        except Exception as e:
            import traceback
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.task_manager.fail_task(task_id, error_msg)
    
    def create_graph(self, name: str) -> str:
        """创建图谱（公开方法）"""
        graph_id = self.client.create_graph(
            name=name,
            description="MiroFish Social Simulation Graph"
        )
        return graph_id
    
    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        """设置图谱本体（公开方法）"""
        # Build entity_types dict from ontology list format
        entity_types = {}
        for entity_def in ontology.get("entity_types", []):
            name = entity_def["name"]
            description = entity_def.get("description", f"A {name} entity.")
            attributes = {}
            for attr_def in entity_def.get("attributes", []):
                attr_name = attr_def["name"]
                attr_desc = attr_def.get("description", attr_name)
                attributes[attr_name] = attr_desc
            entity_types[name] = {
                "description": description,
                "attributes": attributes,
            }

        # Build edge_types dict from ontology list format
        edge_types = {}
        for edge_def in ontology.get("edge_types", []):
            name = edge_def["name"]
            description = edge_def.get("description", f"A {name} relationship.")
            attributes = {}
            for attr_def in edge_def.get("attributes", []):
                attr_name = attr_def["name"]
                attr_desc = attr_def.get("description", attr_name)
                attributes[attr_name] = attr_desc
            edge_types[name] = {
                "description": description,
                "attributes": attributes,
            }

        # Pass raw ontology dicts to GraphitiClient
        if entity_types or edge_types:
            self.client.set_ontology(graph_id, entity_types, edge_types)
    
    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None
    ) -> List[str]:
        """分批添加文本到图谱，返回所有 episode 的 uuid 列表"""
        total_chunks = len(chunks)

        def _batch_progress(current: int, total: int):
            """Relay per-episode progress from GraphitiClient to the task callback."""
            if progress_callback:
                progress = current / total if total > 0 else 0
                batch_num = (current - 1) // batch_size + 1
                total_batches = (total + batch_size - 1) // batch_size
                progress_callback(
                    f"处理第 {batch_num}/{total_batches} 批数据 (块 {current}/{total})...",
                    progress
                )

        try:
            episode_uuids = self.client.add_episodes_batch(
                graph_id,
                chunks,
                progress_callback=_batch_progress,
            )
            return episode_uuids
        except Exception as e:
            if progress_callback:
                progress_callback(f"数据发送失败: {str(e)}", 0)
            raise
    
    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        """获取图谱信息"""
        # 获取节点
        nodes = get_all_nodes_paginated(graph_id)

        # 获取边
        edges = get_all_edges_paginated(graph_id)

        # 统计实体类型
        entity_types = set()
        for node in nodes:
            if node.labels:
                for label in node.labels:
                    if label not in ["Entity", "Node"]:
                        entity_types.add(label)

        return GraphInfo(
            graph_id=graph_id,
            node_count=len(nodes),
            edge_count=len(edges),
            entity_types=list(entity_types)
        )
    
    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """
        获取完整图谱数据（包含详细信息）

        Args:
            graph_id: 图谱ID

        Returns:
            包含nodes和edges的字典，包括时间信息、属性等详细数据
        """
        nodes = get_all_nodes_paginated(graph_id)
        edges = get_all_edges_paginated(graph_id)

        # 创建节点映射用于获取节点名称
        node_map = {}
        for node in nodes:
            node_map[node.uuid] = node.name or ""

        nodes_data = []
        for node in nodes:
            created_at = node.created_at
            if created_at:
                created_at = str(created_at)

            nodes_data.append({
                "uuid": node.uuid,
                "name": node.name,
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
                "created_at": created_at,
            })

        edges_data = []
        for edge in edges:
            created_at = edge.created_at
            valid_at = edge.valid_at
            invalid_at = edge.invalid_at
            expired_at = edge.expired_at

            episodes = edge.episodes or []
            if not isinstance(episodes, list):
                episodes = [str(episodes)]
            else:
                episodes = [str(e) for e in episodes]

            fact_type = edge.name or ""

            edges_data.append({
                "uuid": edge.uuid,
                "name": edge.name or "",
                "fact": edge.fact or "",
                "fact_type": fact_type,
                "source_node_uuid": edge.source_node_uuid,
                "target_node_uuid": edge.target_node_uuid,
                "source_node_name": node_map.get(edge.source_node_uuid, ""),
                "target_node_name": node_map.get(edge.target_node_uuid, ""),
                "attributes": edge.attributes or {},
                "created_at": str(created_at) if created_at else None,
                "valid_at": str(valid_at) if valid_at else None,
                "invalid_at": str(invalid_at) if invalid_at else None,
                "expired_at": str(expired_at) if expired_at else None,
                "episodes": episodes,
            })

        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }
    
    def delete_graph(self, graph_id: str):
        """删除图谱"""
        self.client.delete_graph(graph_id)

