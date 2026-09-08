export type TimelinePoint={date:string;publicationCount:number;eventCount:number;ingestionCount:number};
export type OperationsTimelineResponse={generatedAt:string;windowDays:30|90|365;publicationKnownCount:number;publicationUnknownCount:number;archivedDocumentExcludedCount:number;series:TimelinePoint[]};
function record(v:unknown):v is Record<string,unknown>{return typeof v==='object'&&v!==null&&!Array.isArray(v)}
function finite(v:unknown){return typeof v==='number'&&Number.isFinite(v)}
export function isOperationsTimelineWindowDays(value:unknown):value is 30|90|365{return typeof value==='number'&&Number.isInteger(value)&&[30,90,365].includes(value)}
export function normalizeOperationsTimeline(value:unknown):OperationsTimelineResponse{
 if(!record(value)||typeof value.generatedAt!=='string'||!value.generatedAt||!isOperationsTimelineWindowDays(value.windowDays)||!finite(value.publicationKnownCount)||!finite(value.publicationUnknownCount)||!finite(value.archivedDocumentExcludedCount)||!Array.isArray(value.series))throw new Error('Invalid operations timeline payload');
 if(value.series.some(item=>!record(item)||typeof item.date!=='string'||!item.date||!finite(item.publicationCount)||!finite(item.eventCount)||!finite(item.ingestionCount)))throw new Error('Invalid operations timeline payload');
 return value as unknown as OperationsTimelineResponse;
}
