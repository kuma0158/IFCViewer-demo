// 画面表示用の IFC クラス名の日本語ラベル（無いものは英語のまま表示）
const LABELS: Record<string, string> = {
  IfcWall: '壁',
  IfcWallStandardCase: '壁',
  IfcSlab: '床・スラブ',
  IfcRoof: '屋根',
  IfcColumn: '柱',
  IfcBeam: '梁',
  IfcDoor: 'ドア',
  IfcWindow: '窓',
  IfcStair: '階段',
  IfcStairFlight: '階段（段部分）',
  IfcRailing: '手すり',
  IfcCovering: '仕上げ',
  IfcCurtainWall: 'カーテンウォール',
  IfcPlate: 'パネル',
  IfcMember: '部材（胴縁・方立等）',
  IfcFurnishingElement: '家具',
  IfcFurniture: '家具',
  IfcOpeningElement: '開口',
  IfcFooting: '基礎',
  IfcPile: '杭',
  IfcBuildingElementProxy: 'その他部材',
  IfcFlowTerminal: '設備機器',
  IfcFlowSegment: '配管・ダクト',
  IfcFlowFitting: '継手',
  IfcSpace: '空間（部屋）',
}

export function classLabel(ifcClass: string): string {
  return LABELS[ifcClass] ?? ifcClass
}

// プロパティセット名の日本語ラベル（無いものは英語のまま表示）
const PSET_LABELS: Record<string, string> = {
  Pset_WallCommon: '壁の共通プロパティ',
  Pset_SlabCommon: '床・スラブの共通プロパティ',
  Pset_RoofCommon: '屋根の共通プロパティ',
  Pset_ColumnCommon: '柱の共通プロパティ',
  Pset_BeamCommon: '梁の共通プロパティ',
  Pset_DoorCommon: 'ドアの共通プロパティ',
  Pset_WindowCommon: '窓の共通プロパティ',
  Pset_StairCommon: '階段の共通プロパティ',
  Pset_RailingCommon: '手すりの共通プロパティ',
  Pset_CoveringCommon: '仕上げの共通プロパティ',
  Pset_SpaceCommon: '空間の共通プロパティ',
}

export function psetLabel(psetName: string): string {
  return PSET_LABELS[psetName] ?? psetName
}

// プロパティ名の日本語ラベル（Pset_*Common でよく使われるもの）
const PROP_LABELS: Record<string, string> = {
  Reference: '参照記号',
  Status: 'ステータス',
  IsExternal: '外部に面する',
  LoadBearing: '耐力部材',
  FireRating: '耐火等級',
  AcousticRating: '遮音等級',
  ThermalTransmittance: '熱貫流率',
  Combustible: '可燃性',
  SurfaceSpreadOfFlame: '表面の火炎伝播',
  Compartmentation: '防火区画',
  ExtendToStructure: '構造体まで延長',
  PitchAngle: '勾配角度',
  HandicapAccessible: 'バリアフリー対応',
  FireExit: '避難口',
  SecurityRating: '防犯等級',
  Infiltration: '隙間風量',
  GlazingAreaFraction: 'ガラス面積率',
  SmokeStop: '防煙',
  NumberOfRiser: '蹴上げの数',
  NumberOfTreads: '踏面の数',
  RiserHeight: '蹴上げ高さ',
  TreadLength: '踏面の奥行き',
  Height: '高さ',
  Width: '幅',
  Length: '長さ',
  Span: 'スパン',
  Slope: '勾配',
  Roll: '回転角',
}

export function propLabel(propName: string): string {
  return PROP_LABELS[propName] ?? propName
}
