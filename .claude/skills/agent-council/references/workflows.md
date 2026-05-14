# Multi-Agent Collaboration Workflows

## Code Review

```
1. create_conversation  channel=<repo>  name="review-pr-<number>"  participants=[planner, reviewer, coder]
2. coder posts:   "PR #N is ready: <summary of changes>"
3. reviewer posts: "<review findings>"
4. coder posts:   "<response to review>"
5. reviewer posts: "LGTM" or "Changes requested: <list>"
```

## Architecture Discussion

```
1. create_conversation  channel=<repo>  name="arch-<topic>"  participants=[all agents]
2. planner posts:  "Proposal: <description>"
3. each agent posts: their perspective or concerns
4. planner posts:  "Decision: <chosen approach>"
```

## Task Delegation

```
1. planner registers with capabilities=["planning"]
2. specialist registers with capabilities=["<domain>"]
3. planner sends_message → specialist:  "Task: <description>. Report back when done."
4. specialist does the work, then sends_message → planner: "Done: <result summary>"
5. planner reads_inbox and continues orchestration
```

## Parallel Reasoning

```
1. create_conversation  name="debate-<topic>"  participants=[agent-a, agent-b, agent-c]
2. all agents post their independent assessments (read history before each post)
3. moderator agent posts a synthesis
```

## Tips

- Always call get_conversation before posting — read what others have said first.
- Keep messages focused: one idea, one decision, one question per post.
- Use send_message for private coordination; use post_to_conversation for shared discussion.
