// Deduplicated simple lookup — drivers who switched teams
// use their most recent team color as fallback
const DRIVER_COLOR_FALLBACK: Record<string, string> = {
  VER: '#3671C6', PER: '#3671C6', LAW: '#6692FF', HAD: '#6692FF',
  LEC: '#E8002D', SAI: '#E8002D', BEA: '#E8002D',
  HAM: '#E8002D', RUS: '#27F4D2', ANT: '#27F4D2',
  NOR: '#FF8000', PIA: '#FF8000',
  ALO: '#358C75', STR: '#358C75',
  GAS: '#0090FF', OCO: '#0090FF', COL: '#0090FF', DOO: '#0090FF',
  ALB: '#64C4FF', SAR: '#64C4FF', CUB: '#64C4FF',
  MAG: '#B6BABD', HUL: '#B6BABD', BOR: '#B6BABD',
  BOT: '#C92D4B', ZHO: '#C92D4B',
  TSU: '#6692FF', RIC: '#6692FF',
}

export default DRIVER_COLOR_FALLBACK;
