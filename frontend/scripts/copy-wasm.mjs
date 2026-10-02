// web-ifc の WebAssembly ファイルを public/ にコピーする（npm install 時に自動実行）
import { copyFileSync, mkdirSync } from 'node:fs'

mkdirSync('public', { recursive: true })
copyFileSync('node_modules/web-ifc/web-ifc.wasm', 'public/web-ifc.wasm')
console.log('web-ifc.wasm を public/ にコピーしました')
