export type MacroSeriesGroup = "KOREA" | "US_POLICY" | "US_TREASURY";

export type MacroTimeseriesPoint = {
  month: string;
  value: number;
  observationCount: number;
  partial: boolean;
};

export type MacroTimeseriesSeries = {
  code: string;
  name: string;
  group: MacroSeriesGroup;
  source: string;
  unit: "PERCENT";
  validFrom: string;
  sourceVintageAt: string;
  points: MacroTimeseriesPoint[];
};

export type MacroTimeseriesResponse = {
  generatedAt: string;
  availableFrom: string;
  availableThrough: string;
  completeThrough: string;
  series: MacroTimeseriesSeries[];
};

const record = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown, label: string) => { if (typeof value !== "string" || value.trim() === "") throw new Error(`Invalid ${label}`); return value; };
const month = (value: unknown, label: string) => { const result = text(value, label); if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(result)) throw new Error(`Invalid ${label}`); return result; };
const isoDate = (value: unknown, label: string) => { const result = text(value, label); if (!/^\d{4}-\d{2}-\d{2}$/.test(result) || new Date(`${result}T00:00:00Z`).toISOString().slice(0, 10) !== result) throw new Error(`Invalid ${label}`); return result; };
const timestamp = (value: unknown, label: string) => { const result = text(value, label); if (Number.isNaN(Date.parse(result))) throw new Error(`Invalid ${label}`); return result; };
const finite = (value: unknown, label: string) => { if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`Invalid ${label}`); return value; };
const count = (value: unknown, label: string) => { const result = finite(value, label); if (!Number.isInteger(result) || result < 1) throw new Error(`Invalid ${label}`); return result; };
const groups = new Set<MacroSeriesGroup>(["KOREA", "US_POLICY", "US_TREASURY"]);

export function normalizeMacroTimeseries(value: unknown): MacroTimeseriesResponse {
  if (!record(value) || !Array.isArray(value.series)) throw new Error("Invalid macro timeseries");
  const availableFrom = month(value.availableFrom, "availableFrom");
  const availableThrough = month(value.availableThrough, "availableThrough");
  const completeThrough = month(value.completeThrough, "completeThrough");
  if (availableFrom > completeThrough || completeThrough > availableThrough) throw new Error("Invalid macro coverage");
  const seen = new Set<string>();
  const series = value.series.map((item, seriesIndex) => {
    if (!record(item) || !Array.isArray(item.points)) throw new Error(`Invalid series.${seriesIndex}`);
    const code = text(item.code, `series.${seriesIndex}.code`);
    if (seen.has(code)) throw new Error("Duplicate macro series");
    seen.add(code);
    const group = text(item.group, `series.${seriesIndex}.group`) as MacroSeriesGroup;
    if (!groups.has(group)) throw new Error(`Invalid series.${seriesIndex}.group`);
    const rawPoints = item.points as unknown[];
    const points = rawPoints.map((point, pointIndex) => {
      if (!record(point)) throw new Error(`Invalid series.${seriesIndex}.points.${pointIndex}`);
      const partial = point.partial;
      if (typeof partial !== "boolean") throw new Error("Invalid partial-month flag");
      const parsed = {
        month: month(point.month, `series.${seriesIndex}.points.${pointIndex}.month`),
        value: finite(point.value, `series.${seriesIndex}.points.${pointIndex}.value`),
        observationCount: count(point.observationCount, `series.${seriesIndex}.points.${pointIndex}.observationCount`),
        partial,
      };
      if (parsed.partial !== (parsed.month > completeThrough)) throw new Error("Invalid partial-month flag");
      if (pointIndex > 0 && parsed.month <= month((rawPoints[pointIndex - 1] as Record<string, unknown>).month, "previous month")) throw new Error("Invalid point order");
      return parsed;
    });
    if (!points.length || points[0].month < availableFrom || points.at(-1)!.month > availableThrough) throw new Error("Invalid series coverage");
    return {
      code,
      name: text(item.name, `series.${seriesIndex}.name`),
      group,
      source: text(item.source, `series.${seriesIndex}.source`),
      unit: text(item.unit, `series.${seriesIndex}.unit`) as "PERCENT",
      validFrom: isoDate(item.validFrom, `series.${seriesIndex}.validFrom`),
      sourceVintageAt: timestamp(item.sourceVintageAt, `series.${seriesIndex}.sourceVintageAt`),
      points,
    };
  });
  if (series.some((item) => item.unit !== "PERCENT")) throw new Error("Invalid macro unit");
  return {
    generatedAt: timestamp(value.generatedAt, "generatedAt"),
    availableFrom,
    availableThrough,
    completeThrough,
    series,
  };
}
