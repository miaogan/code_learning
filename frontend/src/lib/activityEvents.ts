/**
 * r138 活跃日刷新信号：写侧完成后发一声，顶栏徽章立即重取。
 *
 * 用 `window` 自定义事件而不是 Context——发点分布在面试/笔试/演武/学堂/历史删除
 * 五处，徽章挂在 App 壳上，彼此不是父子关系；事件总线零依赖、失败也不影响业务主流程。
 */

export const ACTIVITY_CHANGED_EVENT = 'skillcoach:activity-changed'

export function notifyActivityChanged(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new Event(ACTIVITY_CHANGED_EVENT))
}

/** 同时监听显式事件与窗口重新聚焦：跨天/跨设备回来也能刷新，不必整页刷新。 */
export function onActivityChanged(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(ACTIVITY_CHANGED_EVENT, listener)
  window.addEventListener('focus', listener)
  return () => {
    window.removeEventListener(ACTIVITY_CHANGED_EVENT, listener)
    window.removeEventListener('focus', listener)
  }
}
