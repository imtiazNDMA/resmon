export type SarCompositeId =
  | "vh"
  | "vv"
  | "false_color"
  | "water_class"
  | "vv_vh_contrast";

export const SAR_COMPOSITES: Array<{ id: SarCompositeId; name: string }> = [
  { id: "vh", name: "VH Water" },
  { id: "vv", name: "VV Structure" },
  { id: "false_color", name: "False-color SAR" },
  { id: "water_class", name: "Water / Non-water" },
  { id: "vv_vh_contrast", name: "VV/VH Contrast" },
];

export const DEFAULT_SAR_COMPOSITE: SarCompositeId = "vh";
