import {AUTH_REJECTED_MESSAGE,createSessionToken,isValidEmail,isValidSessionSecret,normalizeEmail,SESSION_COOKIE,SESSION_MAX_AGE_SECONDS,shouldUseSecureCookie} from "@/lib/server/auth-session";
import {executeAuthSql,executeAuthWriteSql} from "@/lib/server/db";
import {findAllowedSubjectId} from "@/lib/server/email-allowlist";
import {clearLoginAttempts,consumeLoginAttempts,loginRateLimitKeys} from "@/lib/server/login-rate-limit";
export const runtime="nodejs";
const NO_STORE_HEADERS={"Cache-Control":"no-store"};
export const AUTH_INFRASTRUCTURE_MESSAGE="인증 서버에 연결하지 못했습니다. 이메일 승인 여부와는 별개의 연결 문제입니다. 잠시 후 다시 시도해 주세요.";
const MAX_LOGIN_BODY_BYTES=4*1024;
async function readLimitedBody(request:Request){const declared=Number(request.headers.get("content-length"));if(Number.isFinite(declared)&&declared>MAX_LOGIN_BODY_BYTES)return null;if(!request.body)return new Uint8Array();const reader=request.body.getReader(),chunks:Uint8Array[]=[];let total=0;while(true){const {done,value}=await reader.read();if(done)break;total+=value.byteLength;if(total>MAX_LOGIN_BODY_BYTES){await reader.cancel();return null}chunks.push(value)}const body=new Uint8Array(total);let offset=0;for(const chunk of chunks){body.set(chunk,offset);offset+=chunk.byteLength}return body}
export async function POST(request:Request){
 const sessionSecret=process.env.DASHBOARD_SESSION_SECRET;
 if(!sessionSecret||!isValidSessionSecret(sessionSecret))return Response.json({error:"접근 인증이 구성되지 않았습니다."},{status:503,headers:NO_STORE_HEADERS});
 let email="";
 try{const bytes=await readLimitedBody(request);if(!bytes)return Response.json({error:"요청 크기가 너무 큽니다."},{status:413,headers:NO_STORE_HEADERS});const body=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes)) as {email?:unknown};email=normalizeEmail(typeof body.email==="string"?body.email:"")}catch{return Response.json({error:"잘못된 요청입니다."},{status:400,headers:NO_STORE_HEADERS})}
 let rateKeys:string[]=[];
 try{rateKeys=await loginRateLimitKeys(request,sessionSecret,email);if(await consumeLoginAttempts(executeAuthWriteSql,rateKeys))return Response.json({error:"로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요."},{status:429,headers:{...NO_STORE_HEADERS,"Retry-After":"900"}})}catch{console.error("Dashboard login rate limit failed");return Response.json({error:AUTH_INFRASTRUCTURE_MESSAGE,code:"AUTH_INFRASTRUCTURE_UNAVAILABLE"},{status:503,headers:NO_STORE_HEADERS})}
 if(!isValidEmail(email))return Response.json({error:AUTH_REJECTED_MESSAGE},{status:401,headers:NO_STORE_HEADERS});
 let subjectId:string|null=null;
 try{subjectId=await findAllowedSubjectId(executeAuthSql,email)}catch{console.error("Dashboard email allowlist lookup failed");return Response.json({error:AUTH_INFRASTRUCTURE_MESSAGE,code:"AUTH_INFRASTRUCTURE_UNAVAILABLE"},{status:503,headers:NO_STORE_HEADERS})}
 if(!subjectId)return Response.json({error:AUTH_REJECTED_MESSAGE},{status:401,headers:NO_STORE_HEADERS});
 try{await clearLoginAttempts(executeAuthWriteSql,rateKeys)}catch{console.error("Dashboard login rate limit reset failed")}
 const token=await createSessionToken(subjectId,sessionSecret),secure=shouldUseSecureCookie(request.url);const cookie=`${SESSION_COOKIE}=${token}; Path=/; Max-Age=${SESSION_MAX_AGE_SECONDS}; HttpOnly; SameSite=Lax${secure?"; Secure":""}`;return Response.json({ok:true},{headers:{"Set-Cookie":cookie,...NO_STORE_HEADERS}})
}
