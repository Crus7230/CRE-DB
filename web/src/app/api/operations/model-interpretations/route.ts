import { getCachedModelInterpretations } from "@/lib/server/market-data-cache";
export const runtime="nodejs";
export async function GET(request:Request){try{const limit=Number(new URL(request.url).searchParams.get("limit")||20);return Response.json(await getCachedModelInterpretations(limit),{headers:{"Cache-Control":"private, max-age=60"}})}catch(error){console.error("model interpretations failed",error instanceof Error?error.message:"unknown");return Response.json({error:"MODEL_INTERPRETATIONS_FAILED"},{status:500})}}
