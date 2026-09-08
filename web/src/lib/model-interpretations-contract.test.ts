import { describe,expect,it } from "vitest";
import { normalizeModelInterpretations } from "@/lib/model-interpretations-contract";
const provenance={modelVersion:"M1",embeddingVersion:"E1",promptVersion:"P1",promptHash:"a".repeat(64)};
describe("normalizeModelInterpretations",()=>{
 it("requires complete version provenance and preserves review status",()=>{ const value=normalizeModelInterpretations({generatedAt:"2026",models:[{modelRegistryId:"m1",providerCode:"P",modelName:"M",statusCode:"ENABLED",...provenance}],statusCounts:[{status:"DRAFT",count:1}],interpretations:[{interpretationId:"i1",signalId:"s1",status:"DRAFT",headline:"h",narrative:"n",generatedAt:"2026",inputHash:"b".repeat(64),outputHash:"c".repeat(64),model:{modelRegistryId:"m1",providerCode:"P",modelName:"M",statusCode:"ENABLED",...provenance},evidence:[]}]}); expect(value.interpretations[0].status).toBe("DRAFT"); });
 it("rejects unversioned output",()=>expect(()=>normalizeModelInterpretations({generatedAt:"2026",models:[],statusCounts:[],interpretations:[{interpretationId:"i",signalId:"s",status:"DRAFT",headline:"h",narrative:"n",generatedAt:"2026",inputHash:"x",outputHash:"y",model:{},evidence:[]}]})).toThrow());
});
