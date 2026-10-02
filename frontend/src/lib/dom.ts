/**
 * DOM 生成の小さなヘルパー（フレームワークを使わずに画面を組み立てる）
 *
 * 文字列はすべて textContent として入れる（innerHTML は使わない）。
 * IFC 内の名前やプロパティ値はファイル作成者が自由に書ける値なので、
 * HTML として解釈させると XSS の原因になるため。
 */

type Child = Node | string | null | undefined | false

export interface ElOptions {
  class?: string
  title?: string
  attrs?: Record<string, string>
}

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  options: ElOptions = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  if (options.class) node.className = options.class
  if (options.title) node.title = options.title
  for (const [name, value] of Object.entries(options.attrs ?? {})) node.setAttribute(name, value)
  append(node, ...children)
  return node
}

/** null / undefined / false は無視して子要素を追加（条件付き表示を書きやすくするため） */
export function append(parent: Node, ...children: Child[]): void {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue
    parent.appendChild(typeof c === 'string' ? document.createTextNode(c) : c)
  }
}

/** 中身を差し替える（再描画用） */
export function replaceChildren(parent: Element, ...children: Child[]): void {
  parent.replaceChildren()
  append(parent, ...children)
}
