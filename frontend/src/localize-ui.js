const ORIGINAL_TEXT = new WeakMap()
const ATTR_SOURCE_PREFIX = 'data-miroloc-source-'
const ATTRIBUTE_NAMES = ['placeholder', 'title', 'aria-label']

const FA_EXACT = new Map([
  ['MIROFISH', 'گنتور میروفیش'],
  ['MiroFish', 'گنتور میروفیش'],
  ['Prediction Report', 'گزارش تحلیلی'],
  ['Interactive Tools', 'ابزارهای تعاملی'],
  ['Waiting for Report Agent...', 'در انتظار عامل گزارش...'],
  ['Refresh', 'به‌روزرسانی'],
  ['Graph Relationship Visualization', 'نمایش رابطه‌های گراف'],
  ['Node Details', 'جزئیات گره'],
  ['Name:', 'نام:'],
  ['UUID:', 'شناسه:'],
  ['Created:', 'ایجاد شده:'],
  ['Properties:', 'ویژگی‌ها:'],
  ['Summary:', 'خلاصه:'],
  ['Labels:', 'برچسب‌ها:'],
  ['Type:', 'نوع:'],
  ['Ready', 'آماده'],
  ['Processing', 'در حال پردازش'],
  ['Completed', 'تکمیل شد'],
  ['Generating', 'در حال تولید'],
  ['图谱', 'گراف'],
  ['双栏', 'دو ستونه'],
  ['工作台', 'کارگاه'],
  ['图谱构建', 'ساخت گراف'],
  ['环境搭建', 'آماده‌سازی محیط'],
  ['开始模拟', 'شروع شبیه‌سازی'],
  ['报告生成', 'تولید گزارش'],
  ['深度互动', 'تعامل عمیق'],
  ['系统状态', 'وضعیت سامانه'],
  ['准备就绪', 'آماده برای تحلیل'],
  ['工作流序列', 'دنبالهٔ جریان کار'],
  ['加载中...', 'در حال بارگذاری...'],
  ['推演记录', 'سوابق شبیه‌سازی'],
  ['模拟需求', 'نیاز شبیه‌سازی'],
  ['关联文件', 'فایل‌های پیوست'],
  ['暂无关联文件', 'هنوز فایلی ثبت نشده است'],
  ['推演回放', 'بازپخش شبیه‌سازی'],
  ['分析报告', 'گزارش تحلیلی'],
  ['Agent 配置', 'پیکربندی عامل‌ها'],
  ['未知职业', 'حرفه نامشخص'],
  ['暂无简介', 'هنوز معرفی ثبت نشده است'],
  ['Simulation ID', 'شناسه شبیه‌سازی'],
  ['Task ID', 'شناسه وظیفه'],
  ['Project ID', 'شناسه پروژه'],
  ['Graph ID', 'شناسه گراف'],
])

const FA_SUBSTRINGS = [
  ['访问我们的Github主页', 'مشاهده مخزن GitHub'],
  ['简洁通用的群体智能引擎', 'موتور جمعی هوشمند و متن‌باز'],
  ['上传任意报告', 'هر گزارش یا سندی را بارگذاری کنید'],
  ['即刻推演未来', 'سناریوهای آینده را فوراً شبیه‌سازی کنید'],
  ['拖拽文件上传', 'فایل را بکشید و رها کنید'],
  ['或点击浏览文件系统', 'یا برای انتخاب فایل کلیک کنید'],
  ['输入参数', 'پارامترها'],
  ['模拟提示词', 'دستور شبیه‌سازی'],
  ['启动引擎', 'شروع موتور'],
  ['初始化中...', 'در حال مقداردهی اولیه...'],
  ['刷新图谱', 'به‌روزرسانی گراف'],
  ['图谱数据加载中...', 'داده‌های گراف در حال بارگذاری است...'],
  ['生成完成后将自动开始构建图谱', 'پس از تکمیل، ساخت گراف به‌صورت خودکار آغاز می‌شود'],
  ['与Report Agent对话', 'گفت‌وگو با عامل گزارش'],
  ['与世界中任意个体对话', 'گفت‌وگو با هر عامل در جهان شبیه‌سازی'],
  ['发送问卷调查到世界中', 'ارسال پرسش‌نامه به جهان شبیه‌سازی'],
  ['选择对话对象', 'انتخاب مخاطب'],
  ['与模拟个体对话，了解他们的观点', 'با عامل‌های شبیه‌سازی گفت‌وگو کنید و دیدگاه آن‌ها را ببینید'],
  ['开始生成结果报告', 'شروع تولید گزارش نهایی'],
  ['启动中...', 'در حال شروع...'],
  ['加载报告数据', 'در حال بارگذاری داده گزارش'],
  ['项目加载成功', 'پروژه با موفقیت بارگذاری شد'],
  ['图谱加载失败', 'بارگذاری گراف شکست خورد'],
  ['图谱数据加载成功', 'داده‌های گراف بارگذاری شد'],
  ['现实种子', 'بذرهای واقعیت'],
  ['支持格式:', 'فرمت‌های پشتیبانی‌شده:'],
  ['预测引擎待命中，可上传多份非结构化数据以初始化模拟序列', 'موتور تحلیل آماده است؛ چندین سند را برای ساخت سناریو و شبیه‌سازی بارگذاری کنید'],
  ['低成本', 'هزینه پایین'],
  ['高可用', 'پایدار و مقیاس‌پذیر'],
  ['常规模拟平均5$/次', 'شبیه‌سازی سبک با هزینه معقول'],
  ['最多百万级Agent模拟', 'پشتیبانی از جمعیت عامل‌های بسیار زیاد'],
]

const EN_EXACT = new Map([
  ['MIROFISH', 'Gantor MiroFish'],
  ['MiroFish', 'Gantor MiroFish'],
  ['图谱', 'Graph'],
  ['双栏', 'Split'],
  ['工作台', 'Workbench'],
  ['图谱构建', 'Graph Build'],
  ['环境搭建', 'Environment Setup'],
  ['开始模拟', 'Start Simulation'],
  ['报告生成', 'Generate Report'],
  ['深度互动', 'Deep Interaction'],
  ['系统状态', 'System Status'],
  ['准备就绪', 'Ready'],
  ['工作流序列', 'Workflow Sequence'],
  ['推演记录', 'Simulation History'],
  ['模拟需求', 'Simulation Requirement'],
  ['关联文件', 'Attached Files'],
  ['分析报告', 'Analytical Report'],
  ['Simulation ID', 'Simulation ID'],
  ['Task ID', 'Task ID'],
  ['Project ID', 'Project ID'],
  ['Graph ID', 'Graph ID'],
])

const EN_SUBSTRINGS = [
  ['访问我们的Github主页', 'Visit the GitHub repository'],
  ['简洁通用的群体智能引擎', 'A concise, general-purpose swarm intelligence engine'],
  ['上传任意报告', 'Upload any report'],
  ['即刻推演未来', 'Simulate plausible futures instantly'],
  ['拖拽文件上传', 'Drag files here to upload'],
  ['或点击浏览文件系统', 'or click to browse your files'],
  ['输入参数', 'Input Parameters'],
  ['模拟提示词', 'Simulation Prompt'],
  ['启动引擎', 'Launch Engine'],
  ['初始化中...', 'Initializing...'],
  ['现实种子', 'Reality Seeds'],
  ['支持格式:', 'Supported formats:'],
  ['图谱数据加载中...', 'Loading graph data...'],
  ['低成本', 'Low Cost'],
  ['高可用', 'High Availability'],
]

const SUBSTRING_MAP = { fa: FA_SUBSTRINGS, en: EN_SUBSTRINGS, zh: [] }
const EXACT_MAP = { fa: FA_EXACT, en: EN_EXACT, zh: new Map() }

const translateText = (value, locale) => {
  if (!value || !value.trim() || locale === 'zh') return value
  const trimmed = value.trim()
  const exact = EXACT_MAP[locale]
  if (exact?.has(trimmed)) {
    return value.replace(trimmed, exact.get(trimmed))
  }

  let result = value
  for (const [from, to] of SUBSTRING_MAP[locale] || []) {
    result = result.split(from).join(to)
  }

  return result
    .replace(/Step (\d+)\/5/g, locale === 'fa' ? 'مرحله $1 از 5' : 'Step $1/5')
    .replace(/(\d+)\s*节点/g, locale === 'fa' ? '$1 گره' : '$1 nodes')
    .replace(/(\d+)\s*关系/g, locale === 'fa' ? '$1 رابطه' : '$1 relations')
    .replace(/\+(\d+)\s*个文件/g, locale === 'fa' ? '+$1 فایل' : '+$1 files')
    .replace(/\/ v0\.1-预览版/g, locale === 'fa' ? '/ نسخه پیش‌نمایش' : '/ preview build')
}

const getSourceText = (node) => {
  if (!ORIGINAL_TEXT.has(node)) {
    ORIGINAL_TEXT.set(node, node.nodeValue || '')
  }
  return ORIGINAL_TEXT.get(node) || ''
}

const attrSourceKey = (attr) => `${ATTR_SOURCE_PREFIX}${attr}`

const localizeTextNode = (node, locale) => {
  const source = getSourceText(node)
  const translated = translateText(source, locale)
  if (translated !== node.nodeValue) node.nodeValue = translated
}

const localizeElementAttributes = (element, locale) => {
  ATTRIBUTE_NAMES.forEach((attr) => {
    const sourceKey = attrSourceKey(attr)
    const current = element.getAttribute(attr)
    if (current == null) return
    if (!element.hasAttribute(sourceKey)) {
      element.setAttribute(sourceKey, current)
    }
    const source = element.getAttribute(sourceKey) || current
    const translated = translateText(source, locale)
    if (translated !== current) element.setAttribute(attr, translated)
  })
}

const walkAndLocalize = (root, locale) => {
  if (!root) return
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let node = walker.nextNode()
  while (node) {
    localizeTextNode(node, locale)
    node = walker.nextNode()
  }
  if (root instanceof Element) {
    localizeElementAttributes(root, locale)
    root.querySelectorAll('*').forEach((element) => localizeElementAttributes(element, locale))
  }
}

export function installUiLocalization(root, getLocale, onLocaleChange) {
  let activeLocale = getLocale()
  const relocalize = () => {
    activeLocale = getLocale()
    walkAndLocalize(root, activeLocale)
  }

  relocalize()

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      mutation.addedNodes.forEach((node) => {
        if (node.nodeType === Node.TEXT_NODE) {
          localizeTextNode(node, activeLocale)
          return
        }
        if (node instanceof Element) {
          walkAndLocalize(node, activeLocale)
        }
      })
      if (mutation.type === 'characterData' && mutation.target.nodeType === Node.TEXT_NODE) {
        localizeTextNode(mutation.target, activeLocale)
      }
    }
  })

  observer.observe(root, {
    childList: true,
    subtree: true,
    characterData: true,
  })

  const unsubscribe = onLocaleChange(() => relocalize())
  return () => {
    observer.disconnect()
    unsubscribe()
  }
}
