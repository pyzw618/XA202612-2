---
description: Inject relevant MemoryHub context for the current question
agent: build
---

Read the following durable context before answering. Treat it as a hint and verify it against the current task.

!`memoryhub --compact context "$ARGUMENTS" --max-chars 4000`
