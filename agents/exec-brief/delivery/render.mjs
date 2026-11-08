// Exec Brief renderer: json-render spec in (stdin), Slack Block Kit out (stdout).
// toCard validates every element against the component catalog and enforces platform limits, then Chat SDK's
// Slack adapter converts the card to native blocks (tables and charts included). Python posts the result.
// Input: {"spec": {...}, "limits": {"tables": 1}}  Output: {"blocks": [...], "text": "..."}
import { cardToBlockKit, cardToFallbackText } from "@chat-adapter/slack";
import { CardSpecError, toCard } from "@json-render/chat";

let raw = "";
for await (const chunk of process.stdin) raw += chunk;

try {
  const { spec, limits } = JSON.parse(raw);
  const card = toCard(spec, { limits: limits ?? { tables: 1 } });
  process.stdout.write(JSON.stringify({ blocks: cardToBlockKit(card), text: cardToFallbackText(card) }));
} catch (err) {
  const issues = err instanceof CardSpecError ? err.issues : [String(err?.message ?? err)];
  process.stderr.write(JSON.stringify({ error: "render failed", issues }));
  process.exit(1);
}
