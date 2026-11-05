import { beforeEach, describe, expect, it } from 'vitest'
import { consumeResumePrompt, resetResumePrompt } from '../lib/resumePrompt'

describe('resumePrompt', () => {
  beforeEach(() => {
    resetResumePrompt()
  })

  it('同一会话只弹一次', () => {
    expect(consumeResumePrompt()).toBe(true)
    expect(consumeResumePrompt()).toBe(false)
    expect(consumeResumePrompt()).toBe(false)
  })

  it('登出重置后下一位用户仍会看到一次引导', () => {
    consumeResumePrompt()
    resetResumePrompt()
    expect(consumeResumePrompt()).toBe(true)
  })
})
