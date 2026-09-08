import { getCategoryIndex, type CategorySqlExecutor } from "../src/lib/server/category-index";
import { createSqlExecutor, createTursoClient } from "./libsql-client.mjs";

const client = createTursoClient();
const execute = createSqlExecutor(client) as CategorySqlExecutor;
try {
  const result = await getCategoryIndex(execute);
  console.log(JSON.stringify({
    groups: result.groups.map((group) => ({
      group: group.group,
      total: group.items.reduce((sum, item) => sum + item.itemCount, 0),
    })),
  }));
} finally {
  client.close();
}
