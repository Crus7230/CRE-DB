import fs from "node:fs";
import postgres from "postgres";
import { getCategoryIndex, type CategorySqlExecutor } from "../src/lib/server/category-index";
const env=fs.readFileSync(String.raw`C:\10137_WorkSpace\env\.env.supabase.local`,"utf8").split(/\r?\n/).reduce<Record<string,string>>((a,l)=>{const m=l.match(/^([^#=]+)=(.*)$/);if(m)a[m[1].trim()]=m[2].trim().replace(/^['"]|['"]$/g,"");return a;},{});
const sql=postgres(env.SUPABASE_DB_URL,{max:1,prepare:false});
const execute: CategorySqlExecutor=async(text,values)=>({rows:[...(await sql.unsafe(text,[...values]))] as unknown as Array<{payload:unknown}>});
try { const result=await getCategoryIndex(execute); console.log(JSON.stringify({groups:result.groups.map(g=>({group:g.group,total:g.items.reduce((n,i)=>n+i.itemCount,0)}))})); } finally { await sql.end(); }
