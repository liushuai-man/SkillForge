// Display labels only: stored references and API enums keep their original values.
export const triggerLabel = (value: string) => ({
  init: '首次纳管', manual: '手动保存', watch: '自动保存',
} as Record<string, string>)[value] ?? `其他来源（${value}）`

export const refLabel = (value: string) => value === 'baseline' ? '最近锚点' : value
