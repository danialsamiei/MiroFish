const RTL_CHAR_RE = /[\u0590-\u05FF\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]/
const LTR_CHAR_RE = /[A-Za-z\u00C0-\u024F]/
const MANAGED_ATTR = 'data-miro-bidi'
const MANAGED_FLAG_ATTR = 'data-miro-bidi-managed'
const ORIGINAL_DIR_ATTR = 'data-miro-bidi-original-dir'

const CANDIDATE_SELECTOR = [
  'h1','h2','h3','h4','h5','h6','p','span','strong','small','label','button','a','li',
  'dt','dd','blockquote','figcaption','summary','caption','th','td',
  '.panel-title','.step-title','.step-desc','.section-title','.section-desc',
  '.metric-value','.metric-label','.console-label','.console-meta','.upload-title',
  '.upload-hint','.file-name',
].join(',')

const SKIP_CLOSEST_SELECTOR = [
  'script','style','svg','math','code','pre','kbd','samp','[data-miro-bidi-skip]',
].join(',')

const classifyDirection = (text) => {
  const normalized = (text || '').replace(/\s+/g, ' ').trim()
  if (!normalized) return null
  const chars = Array.from(normalized)
  const first = chars.find((char) => RTL_CHAR_RE.test(char) || LTR_CHAR_RE.test(char)) || null
  const last = [...chars].reverse().find((char) => RTL_CHAR_RE.test(char) || LTR_CHAR_RE.test(char)) || null
  if ((first && RTL_CHAR_RE.test(first)) || (last && RTL_CHAR_RE.test(last))) return 'rtl'
  if ((first && LTR_CHAR_RE.test(first)) || (last && LTR_CHAR_RE.test(last))) return 'ltr'
  return null
}

const applyManagedDirection = (element, direction) => {
  const isManaged = element.getAttribute(MANAGED_FLAG_ATTR) === '1'
  if (direction === 'rtl') {
    if (!isManaged && element.hasAttribute('dir')) {
      element.setAttribute(ORIGINAL_DIR_ATTR, element.getAttribute('dir') || '')
    }
    element.setAttribute(MANAGED_ATTR, 'rtl')
    element.setAttribute(MANAGED_FLAG_ATTR, '1')
    element.setAttribute('dir', 'rtl')
    return
  }
  if (!isManaged) return
  const originalDir = element.getAttribute(ORIGINAL_DIR_ATTR)
  if (originalDir) element.setAttribute('dir', originalDir)
  else element.removeAttribute('dir')
  element.removeAttribute(MANAGED_ATTR)
  element.removeAttribute(MANAGED_FLAG_ATTR)
  element.removeAttribute(ORIGINAL_DIR_ATTR)
}

const processElement = (element) => {
  if (!(element instanceof HTMLElement)) return
  if (element.closest(SKIP_CLOSEST_SELECTOR)) return
  const text = element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement
    ? (element.placeholder || element.value || '')
    : (element.textContent || '')
  applyManagedDirection(element, classifyDirection(text))
}

const scanRoot = (root) => {
  if (root instanceof HTMLElement && root.matches(CANDIDATE_SELECTOR)) processElement(root)
  if (root && 'querySelectorAll' in root) {
    root.querySelectorAll(CANDIDATE_SELECTOR).forEach(processElement)
  }
}

export const installBidiTextEnhancer = (root = document.body) => {
  if (typeof window === 'undefined' || !root) return () => {}
  let queued = false
  const dirtyRoots = new Set([root])

  const flush = () => {
    queued = false
    const roots = Array.from(dirtyRoots)
    dirtyRoots.clear()
    roots.forEach(scanRoot)
  }

  const schedule = (nextRoot) => {
    dirtyRoots.add(nextRoot)
    if (queued) return
    queued = true
    window.requestAnimationFrame(flush)
  }

  schedule(root)

  const observer = new MutationObserver((records) => {
    records.forEach((record) => {
      if (record.type === 'characterData') {
        if (record.target.parentElement) schedule(record.target.parentElement)
        return
      }
      record.addedNodes.forEach((node) => {
        if (node instanceof HTMLElement) schedule(node)
      })
      if (record.target instanceof HTMLElement) schedule(record.target)
    })
  })

  observer.observe(root, {
    childList: true,
    subtree: true,
    characterData: true,
  })

  return () => observer.disconnect()
}
