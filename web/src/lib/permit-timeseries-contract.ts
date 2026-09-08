export const PERMIT_GROUPS = [
  "EVENT_TYPE",
  "ASSET_TYPE",
  "DISTRICT",
  "CONSTRUCTION_ACTION",
] as const;
export type PermitGroup = (typeof PERMIT_GROUPS)[number];

export const PERMIT_EVENT_TYPES = ["PERMIT", "ACTUAL_START", "USE_APPROVAL"] as const;
export type PermitEventType = (typeof PERMIT_EVENT_TYPES)[number];

export const PERMIT_ASSET_TYPES = [
  "OFFICE",
  "LOGISTICS",
  "DATA_CENTER",
  "HOTEL",
  "RETAIL",
  "MIXED_USE",
  "OTHER_COMMERCIAL",
  "NONCOMMERCIAL",
  "RESIDENTIAL",
  "UNKNOWN",
] as const;
export type PermitAssetType = (typeof PERMIT_ASSET_TYPES)[number];

export const PERMIT_CONSTRUCTION_ACTIONS = [
  "NEW_SUPPLY",
  "AREA_EXPANSION",
  "REDEVELOPMENT",
  "USE_CONVERSION",
  "OTHER",
] as const;
export type PermitConstructionAction = (typeof PERMIT_CONSTRUCTION_ACTIONS)[number];

export type PermitTimeseriesRequest = {
  groupBy: PermitGroup;
  from: string | null;
  to: string | null;
  eventType: PermitEventType | null;
  assetType: PermitAssetType | null;
  district: string | null;
  constructionAction: PermitConstructionAction | null;
};

export type PermitTimeseriesPoint = {
  month: string;
  permitCount: number;
  totalFloorAreaM2: number;
  missingAreaCount: number;
  invalidAreaCount: number;
};

export type PermitTimeseriesResponse = {
  generatedAt: string;
  sourceAsOfDate: string;
  availableFrom: string;
  availableThrough: string;
  selectedFrom: string;
  selectedThrough: string;
  groupBy: PermitGroup;
  filters: Omit<PermitTimeseriesRequest, "groupBy" | "from" | "to">;
  source: { code: "src_seoul_building_permit"; label: "서울 열린데이터광장" };
  scope: {
    status: "IN_SCOPE";
    completedSnapshotsOnly: true;
    dateRule: "ACTUAL_EVENT_DATE_1900_THROUGH_CURRENT";
  };
  series: Array<{
    key: string;
    label: string;
    points: PermitTimeseriesPoint[];
  }>;
  quality: {
    aggregateRowCount: number;
    permitCount: number;
    totalFloorAreaM2: number;
    missingAreaCount: number;
    invalidAreaCount: number;
  };
};

export class PermitRequestError extends Error {
  readonly code = "INVALID_PERMIT_QUERY";
}

const isoMonth = /^\d{4}-(?:0[1-9]|1[0-2])$/u;

function optionalEnum<T extends string>(
  params: URLSearchParams,
  name: string,
  allowed: readonly T[],
): T | null {
  const value = params.get(name);
  if (value === null || value === "") return null;
  if (!(allowed as readonly string[]).includes(value)) {
    throw new PermitRequestError(`Invalid ${name}`);
  }
  return value as T;
}

function optionalMonth(params: URLSearchParams, name: string): string | null {
  const value = params.get(name);
  if (value === null || value === "") return null;
  if (!isoMonth.test(value)) throw new PermitRequestError(`Invalid ${name}`);
  return value;
}

export function parsePermitTimeseriesRequest(params: URLSearchParams): PermitTimeseriesRequest {
  const groupBy = params.get("groupBy") || "EVENT_TYPE";
  if (!(PERMIT_GROUPS as readonly string[]).includes(groupBy)) {
    throw new PermitRequestError("Invalid groupBy");
  }
  const from = optionalMonth(params, "from");
  const to = optionalMonth(params, "to");
  if (from && to && from > to) throw new PermitRequestError("from must not follow to");
  const districtValue = params.get("district");
  const district = districtValue === null || districtValue.trim() === ""
    ? null
    : districtValue.trim();
  if (district && (district.length > 40 || /[\u0000-\u001f\u007f]/u.test(district))) {
    throw new PermitRequestError("Invalid district");
  }
  return {
    groupBy: groupBy as PermitGroup,
    from,
    to,
    eventType: optionalEnum(params, "eventType", PERMIT_EVENT_TYPES),
    assetType: optionalEnum(params, "assetType", PERMIT_ASSET_TYPES),
    district,
    constructionAction: optionalEnum(
      params,
      "constructionAction",
      PERMIT_CONSTRUCTION_ACTIONS,
    ),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredText(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value !== "string" || !value) throw new Error(`Invalid ${key}`);
  return value;
}

function finiteNumber(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new Error(`Invalid ${key}`);
  }
  return value;
}

export function normalizePermitTimeseries(value: unknown): PermitTimeseriesResponse {
  if (!isRecord(value) || !Array.isArray(value.series)) {
    throw new Error("Invalid permit timeseries payload");
  }
  const groupBy = requiredText(value, "groupBy");
  if (!(PERMIT_GROUPS as readonly string[]).includes(groupBy)) throw new Error("Invalid groupBy");
  if (!isRecord(value.filters) || !isRecord(value.source) || !isRecord(value.scope) || !isRecord(value.quality)) {
    throw new Error("Invalid permit metadata");
  }
  const filters = value.filters;
  const nullableFilter = (key: string) => {
    const item = filters[key];
    if (item === null) return null;
    if (typeof item !== "string") throw new Error(`Invalid ${key}`);
    return item;
  };
  const sourceCode = requiredText(value.source, "code");
  const sourceLabel = requiredText(value.source, "label");
  if (sourceCode !== "src_seoul_building_permit" || sourceLabel !== "서울 열린데이터광장") {
    throw new Error("Invalid permit source");
  }
  if (
    value.scope.status !== "IN_SCOPE"
    || value.scope.completedSnapshotsOnly !== true
    || value.scope.dateRule !== "ACTUAL_EVENT_DATE_1900_THROUGH_CURRENT"
  ) throw new Error("Invalid permit scope");
  return {
    generatedAt: requiredText(value, "generatedAt"),
    sourceAsOfDate: requiredText(value, "sourceAsOfDate"),
    availableFrom: requiredText(value, "availableFrom"),
    availableThrough: requiredText(value, "availableThrough"),
    selectedFrom: requiredText(value, "selectedFrom"),
    selectedThrough: requiredText(value, "selectedThrough"),
    groupBy: groupBy as PermitGroup,
    filters: {
      eventType: nullableFilter("eventType") as PermitEventType | null,
      assetType: nullableFilter("assetType") as PermitAssetType | null,
      district: nullableFilter("district"),
      constructionAction: nullableFilter("constructionAction") as PermitConstructionAction | null,
    },
    source: { code: sourceCode, label: sourceLabel },
    scope: {
      status: "IN_SCOPE",
      completedSnapshotsOnly: true,
      dateRule: "ACTUAL_EVENT_DATE_1900_THROUGH_CURRENT",
    },
    series: value.series.map((rawSeries) => {
      if (!isRecord(rawSeries) || !Array.isArray(rawSeries.points)) throw new Error("Invalid permit series");
      return {
        key: requiredText(rawSeries, "key"),
        label: requiredText(rawSeries, "label"),
        points: rawSeries.points.map((rawPoint) => {
          if (!isRecord(rawPoint)) throw new Error("Invalid permit point");
          const month = requiredText(rawPoint, "month");
          if (!isoMonth.test(month)) throw new Error("Invalid permit month");
          return {
            month,
            permitCount: finiteNumber(rawPoint, "permitCount"),
            totalFloorAreaM2: finiteNumber(rawPoint, "totalFloorAreaM2"),
            missingAreaCount: finiteNumber(rawPoint, "missingAreaCount"),
            invalidAreaCount: finiteNumber(rawPoint, "invalidAreaCount"),
          };
        }),
      };
    }),
    quality: {
      aggregateRowCount: finiteNumber(value.quality, "aggregateRowCount"),
      permitCount: finiteNumber(value.quality, "permitCount"),
      totalFloorAreaM2: finiteNumber(value.quality, "totalFloorAreaM2"),
      missingAreaCount: finiteNumber(value.quality, "missingAreaCount"),
      invalidAreaCount: finiteNumber(value.quality, "invalidAreaCount"),
    },
  };
}
