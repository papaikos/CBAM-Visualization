/** Green → yellow → red map color scale. */

const NO_DATA_COLOR = "#e2e8f0";

export function getColor(value, maxValue) {
  const max = maxValue || 0;
  if (value === null || value === undefined) {
    return NO_DATA_COLOR;
  }
  if (max <= 0) {
    return "rgb(0, 128, 68)";
  }
  const ratio = Math.min(value / max, 1);
  if (ratio <= 0.33) {
    const blend = ratio / 0.33;
    const red = Math.round(255 * blend);
    const green = Math.round(128 + 127 * blend);
    return `rgb(${red}, ${green}, 68)`;
  }
  if (ratio <= 0.66) {
    const blend = (ratio - 0.33) / 0.33;
    const green = Math.round(255 - 100 * blend);
    return `rgb(255, ${green}, 68)`;
  }
  const blend = (ratio - 0.66) / 0.34;
  const red = Math.round(255 - 40 * blend);
  const green = Math.round(155 - 115 * blend);
  const blue = Math.round(68 - 28 * blend);
  return `rgb(${red}, ${green}, ${blue})`;
}

export function toGray(rgbColor) {
  const match = rgbColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
  if (!match) {
    return rgbColor;
  }
  const [red, green, blue] = match.slice(1).map(Number);
  const gray = Math.round(0.299 * red + 0.587 * green + 0.114 * blue);
  return `rgb(${gray}, ${gray}, ${gray})`;
}
