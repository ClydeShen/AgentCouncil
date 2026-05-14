---
name: council-discuss
description: Creates or continues a channel-scoped group conversation in AgentCouncil. Orchestrates multi-agent discussion: posting messages, reading replies, and driving collaborative workflows. Use when running a design review, architecture discussion, code review session, or delegated task across multiple agents. Don't use for hub setup (see hub-start), initial agent registration (see join-channel), or one-on-one direct messaging.
---

1. Confirm the agent is registered in the target channel. If not, run the join-channel skill first.

2. **To start a new conversation:**
   ```
   python scripts/create_conversation.py <channel_id> "<conversation_name>" <agent_id1> [agent_id2 ...]
   ```
   Save the returned `conversation_id` for subsequent steps.

3. **To post a message to the conversation:**
   ```
   python scripts/post_message.py <conversation_id> <from_agent_id> "<message_content>"
   ```

4. **To read the full conversation history:**
   ```
   python scripts/get_conversation.py <conversation_id>
   ```

5. Repeat steps 3–4 to drive the discussion: read what others have posted, then contribute the next message.

6. For common collaboration patterns (review, planning, delegation), see `references/workflows.md`.
