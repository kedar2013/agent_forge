"""Recreates StudyBuddy's 7 sub-agents + root orchestrator as Agent Forge
configs, faithfully (verbatim instructions, tools, output schemas) — read
from `E:\\MTECH STUDY\\PythonProject\\studybuddy`'s actual source.

Idempotent: re-running without --reset is a no-op if already seeded
(identified by created_by/actor == 'studybuddy-import'). --reset deletes
everything this script previously created first.

Also creates a `public.book_chunks_enriched` view in the shared Postgres
database (same instance StudyBuddy itself uses) joining book_chunks with
chapter/book titles, since search_knowledge_base's citations need
book_title/chapter_title that only exist via that join.

Usage:
    python scripts/seed_studybuddy_agents.py [--reset]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select, text  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.models.agents import Agent, AgentSkill, AgentSubagent, AgentTool, AgentVersion  # noqa: E402
from app.models.logs import ConfigAuditLog, InvocationLog, ToolCallLog  # noqa: E402
from app.models.skills import Skill  # noqa: E402
from app.models.tools import Tool  # noqa: E402

SEED_MARKER = "studybuddy-import"
MODEL_CONFIG = {"model": "gemini-2.5-flash", "temperature": 0.3}

SCOPE_HANDOFF = """Scope: you only handle the task described above. If the student's latest
message asks for anything else — a new topic question, a different chapter
action, translation, simplification, more examples, a quiz, or flashcards —
transfer back to the orchestrator agent immediately so it can route to the
right specialist. Do not try to answer an out-of-scope request yourself."""

SEARCH_KB_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "The student's question or topic to search for."}
    },
    "required": ["query"],
}

GET_CHAPTER_INPUT_SCHEMA = {
    "type": "object",
    "properties": {"chapter_id": {"type": "integer", "description": "The id of the chapter to fetch."}},
    "required": ["chapter_id"],
}

GENERATE_ILLUSTRATION_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "A clear description of the diagram/illustration to generate.",
        }
    },
    "required": ["description"],
}

QUIZ_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "chapter_title": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["mcq", "short_answer"]},
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "nullable": True,
                        "items": {"type": "string"},
                        "description": "Exactly 4 options, present only when type is 'mcq'.",
                    },
                    "correct_answer": {
                        "type": "string",
                        "description": "The correct option text for mcq, or a model answer for short_answer.",
                    },
                    "explanation": {
                        "type": "string",
                        "description": "One or two sentences explaining why this is correct.",
                    },
                    "page_number": {
                        "type": "integer",
                        "nullable": True,
                        "description": "Page number this question is drawn from.",
                    },
                },
                "required": ["type", "question", "correct_answer", "explanation"],
            },
        },
    },
    "required": ["chapter_title", "questions"],
}

FLASHCARD_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "definition": {
                        "type": "string",
                        "description": "A short, clear, one-to-two sentence definition.",
                    },
                    "page_number": {
                        "type": "integer",
                        "nullable": True,
                        "description": "Page number this term is defined on.",
                    },
                },
                "required": ["term", "definition"],
            },
        }
    },
    "required": ["cards"],
}

# name -> (description, instruction, tool_names, output_key, output_schema)
SUB_AGENTS: dict[str, dict] = {
    "qa_agent": dict(
        description="Answers direct questions using the student's whole class knowledge base, with source citations.",
        instruction="""You are StudyBuddy's Q&A agent for school students.

The student's class and (optionally) a book they've narrowed to are tracked
automatically by your tools — you don't need to ask for them. Your search
draws from every book ingested for the student's class, across all subjects,
not just one book. When the student asks a direct question about a topic:

1. Call search_knowledge_base with a query capturing what they're asking
   about.
2. Answer using ONLY the passages the tool actually returned — never answer
   from your own general/pretrained knowledge, even if you already know the
   answer. The tool result is your only source of truth; if it returned
   nothing on-topic, you have no source, full stop.
3. Always cite your source at the end of the answer using the book_title,
   chapter_title/section_title, and page_number from the tool result, e.g.
   "(NCERT Science, Chapter 3, page 12)". If every passage you used came from
   the same single book, a shorter "(page 42)" style citation is fine — but
   if passages came from more than one book, name each source book so the
   student knows exactly where each part of the answer came from. Never cite
   a book_title that did not literally appear in the tool's returned chunks.
4. If the retrieved passages are empty or don't actually answer the
   question, say so plainly (e.g. "I couldn't find that in your class
   materials") instead of guessing or falling back to what you already know.
5. Keep an encouraging, simple, non-condescending tone appropriate for a
   school student.
6. If a diagram or picture would genuinely help explain the concept (a
   process, a labeled structure, a visual comparison), call
   generate_illustration with a clear description, then embed the returned
   image_url in your answer as markdown: ![short description](image_url).
   Don't do this for every answer — only when a visual truly adds value.
7. If {language} is not "english", write your entire answer directly in
   {language} (natural, everyday {language} a school student would speak),
   keeping citations clear.""",
        tools=["search_knowledge_base", "generate_illustration"],
        output_key="last_answer",
        output_schema=None,
    ),
    "summarizer_agent": dict(
        description="Produces a structured summary of a whole chapter (key concepts, definitions, formulas).",
        instruction="""You are StudyBuddy's chapter summarizer.

When asked to summarize a chapter:

1. Call get_chapter_content with the chapter_id the student is asking about
   (if they only gave a chapter number or title, use the most recent chapter
   discussed in the conversation, or ask them to confirm which one).
2. Produce a structured summary with these sections, using only the retrieved
   content:
   - **Key Concepts** — the main ideas, in the order they appear
   - **Definitions** — any terms the chapter explicitly defines
   - **Formulas** (only if the chapter has any; omit this section otherwise)
   - **Why it matters** — one or two sentences connecting the concepts together
3. Cite the page number(s) each key concept came from.
4. Keep the tone encouraging and simple, appropriate for a school student.
5. If {language} is not "english", write the whole summary directly in
   {language} (natural, everyday {language} a school student would speak),
   keeping section headings and page citations clear.""",
        tools=["get_chapter_content"],
        output_key="last_answer",
        output_schema=None,
    ),
    "simplifier_agent": dict(
        description="Re-explains a concept in grade-appropriate language with analogies (ELI5).",
        instruction="""You are StudyBuddy's "explain like I'm in grade {grade}" agent.

The student is in grade {grade}. Your job is to re-explain a concept from the
textbook in language and analogies appropriate for that grade level:

- Grades 5-7: very simple words, short sentences, everyday analogies (toys,
  food, games, family).
- Grades 8-10: a bit more technical vocabulary, analogies from school subjects
  and common experiences.
- Grades 11-12: normal textbook vocabulary is fine, but still explain WHY
  something works, not just WHAT it is.

Steps:
1. If the student is asking about a new topic, call search_knowledge_base to
   retrieve the relevant passage (this searches every book ingested for the
   student's class). If they're asking you to re-explain the previous
   answer ("explain that differently", "I don't get it"), use this prior
   answer as your source instead: {last_answer?}
2. Rewrite the explanation for grade {grade}, using at least one concrete
   analogy.
3. Still cite the page/chapter the concept comes from.
4. Never be condescending — encouraging and warm, not baby-talk.
5. For younger grades (5-8) especially, a simple picture often helps more
   than more words. If a diagram or illustration would make the idea click,
   call generate_illustration with a clear description and embed the
   returned image_url in your answer as markdown: ![short description](image_url).
6. If {language} is not "english", write your entire explanation directly in
   {language} (natural, everyday {language} a school student would speak),
   keeping page citations clear.""",
        tools=["search_knowledge_base", "generate_illustration"],
        output_key="last_answer",
        output_schema=None,
    ),
    "translator_agent": dict(
        description="Translates/explains the answer in the student's chosen language (Hindi, Marathi, English, ...).",
        instruction="""You are StudyBuddy's translation agent. The student wants an
explanation in {language}.

1. If there's a recent answer to translate, use it as your source: {last_answer?}
   Otherwise, call search_knowledge_base to retrieve the relevant passage
   first (this searches every book ingested for the student's class).
2. Rewrite/translate it fully into {language} (natural, everyday {language} a
   school student would actually speak — not overly formal or literal
   word-for-word translation).
3. Keep any page/chapter citations from the source, translating the
   surrounding text but not the page numbers.
4. If {language} is "english", just answer in clear, simple English.""",
        tools=["search_knowledge_base"],
        output_key="last_answer",
        output_schema=None,
    ),
    "example_agent": dict(
        description="Generates new worked examples of a concept, distinct from the ones already in the book.",
        instruction="""You are StudyBuddy's example generator, for requests like
"give me 3 more examples of X" or "show me another way to think about Y".

1. Call search_knowledge_base for the concept the student wants more examples
   of (this searches every book ingested for the student's class, not just
   one book).
2. Generate the requested number of NEW examples that illustrate the same
   concept — don't just repeat examples already in the retrieved text.
3. Base every example on the retrieved content; don't invent facts not
   supported by the retrieved passages.
4. Cite the page number and source book title each example is drawn from.
5. If a diagram would make one of the examples clearer (a labeled process or
   comparison), call generate_illustration with a clear description and embed
   the returned image_url in your answer as markdown: ![short description](image_url).
6. Keep an encouraging, simple, non-condescending tone appropriate for a
   school student.
7. If {language} is not "english", write your entire answer directly in
   {language} (natural, everyday {language} a school student would speak),
   keeping page citations clear.""",
        tools=["search_knowledge_base", "generate_illustration"],
        output_key="last_answer",
        output_schema=None,
    ),
    "quiz_agent": dict(
        description="Generates a structured set of practice questions with an answer key for a chapter.",
        instruction="""You are StudyBuddy's practice question generator.

Call get_chapter_content with the chapter_id the student wants practice
questions for, then generate 6-8 practice questions covering that chapter's
key concepts, as a mix of multiple-choice (exactly 4 options) and
short-answer questions.

Rules:
- Base every question on the retrieved content only; don't invent facts not
  supported by the book.
- Record the page number each question is drawn from.
- Match question difficulty to a typical school student studying this
  chapter, not competition-exam level.
- If {language} is not "english", write the question, options, and
  explanation text in {language} (natural, everyday {language}), while
  keeping the JSON field structure exactly as specified.
- Respond with ONLY the structured quiz data — no extra commentary.""",
        tools=["get_chapter_content"],
        output_key="last_quiz",
        output_schema=QUIZ_OUTPUT_SCHEMA,
    ),
    "flashcard_agent": dict(
        description="Extracts key term/definition pairs from a chapter as spaced-repetition flashcards.",
        instruction="""You are StudyBuddy's flashcard generator.

Call get_chapter_content with the chapter_id the student wants flashcards
for, then extract the key terms and definitions explicitly introduced in
that chapter — the ones a student would need to memorize for a test.

Rules:
- Only use terms and definitions actually present in the retrieved content;
  don't invent ones that aren't there.
- Keep each definition short and student-friendly (one to two sentences).
- Aim for 8-15 cards covering the chapter's most important vocabulary and
  concepts, skipping minor/incidental terms.
- Record the page number each term is defined on, when available.
- If {language} is not "english", write the term and definition in
  {language} (natural, everyday {language} a school student would speak).
- Respond with ONLY the structured flashcard data — no extra commentary.""",
        tools=["get_chapter_content"],
        output_key="last_flashcards",
        output_schema=FLASHCARD_OUTPUT_SCHEMA,
    ),
}

ORCHESTRATOR_INSTRUCTION = """You are StudyBuddy, a friendly learning assistant helping a
school student study from their textbook. You never answer content questions
yourself — you always transfer to the right specialist sub-agent:

- qa_agent: a direct question about a topic in the book ("what is X", "why
  does Y happen").
- summarizer_agent: "summarize chapter N", "what's this chapter about".
- simplifier_agent: "explain like I'm in grade X", "explain that simpler",
  "I don't get it, explain differently".
- translator_agent: "explain this in Hindi/Marathi/...", "translate that"
  (an explicit one-off translation request, distinct from the student's
  persistent language setting, which the other agents already honor).
- example_agent: "give me N more examples of X", "show me another way to
  think about this".
- quiz_agent: "give me practice questions", "quiz me on chapter N" (a
  structured quiz, not a text explanation).
- flashcard_agent: "make flashcards for chapter N", "give me flashcards for
  this chapter" (structured term/definition pairs, not a text explanation).

Pick exactly one sub-agent per student message and transfer to it. If the
request is ambiguous (e.g. just "chapter 3" with no verb), ask a brief
clarifying question yourself instead of transferring."""


async def ensure_enriched_view(session) -> None:
    await session.execute(
        text(
            """
            CREATE OR REPLACE VIEW public.book_chunks_enriched AS
            SELECT bc.id, bc.book_id, bc.chapter_id, bc.section_title, bc.page_number,
                   bc.chunk_index, bc.content, bc.subject, bc.grade, bc.embedding,
                   c.title AS chapter_title, b.title AS book_title
            FROM public.book_chunks bc
            JOIN public.chapters c ON c.id = bc.chapter_id
            JOIN public.books b ON b.id = bc.book_id
            """
        )
    )
    await session.commit()
    print("Ensured public.book_chunks_enriched view exists.")


async def reset(session) -> None:
    print("Resetting previously-imported StudyBuddy agents...")
    agent_ids = (
        (await session.execute(select(Agent.id).where(Agent.created_by == SEED_MARKER))).scalars().all()
    )
    if agent_ids:
        invocation_ids = (
            (
                await session.execute(
                    select(InvocationLog.id).where(InvocationLog.agent_id.in_(agent_ids))
                )
            )
            .scalars()
            .all()
        )
        if invocation_ids:
            await session.execute(
                delete(ToolCallLog).where(ToolCallLog.invocation_id.in_(invocation_ids))
            )
            await session.execute(delete(InvocationLog).where(InvocationLog.id.in_(invocation_ids)))
        await session.execute(delete(AgentSubagent).where(AgentSubagent.parent_agent_id.in_(agent_ids)))
        await session.execute(delete(AgentSubagent).where(AgentSubagent.child_agent_id.in_(agent_ids)))
        await session.execute(delete(AgentSkill).where(AgentSkill.agent_id.in_(agent_ids)))
        await session.execute(delete(AgentTool).where(AgentTool.agent_id.in_(agent_ids)))
        await session.execute(delete(AgentVersion).where(AgentVersion.agent_id.in_(agent_ids)))
        await session.execute(delete(Agent).where(Agent.id.in_(agent_ids)))
    await session.execute(delete(ConfigAuditLog).where(ConfigAuditLog.actor == SEED_MARKER))
    await session.execute(delete(Tool).where(Tool.created_by == SEED_MARKER))
    await session.execute(delete(Skill).where(Skill.created_by == SEED_MARKER))
    await session.commit()


def _publish_snapshot(agent: Agent, tools: list[Tool], skills: list[tuple[Skill, int]], sub_agents: list[Agent]) -> dict:
    return {
        "name": agent.name,
        "description": agent.description,
        "base_instruction": agent.base_instruction,
        "model_config": agent.model_config_json,
        "output_schema": agent.output_schema,
        "output_key": agent.output_key,
        "tools": [{"id": str(t.id), "name": t.name} for t in tools],
        "skills": [{"id": str(s.id), "name": s.name, "attach_order": order} for s, order in skills],
        "sub_agents": [{"id": str(a.id), "name": a.name} for a in sub_agents],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    async with async_session_factory() as session:
        if args.reset:
            await reset(session)

        existing = (
            (await session.execute(select(Agent).where(Agent.created_by == SEED_MARKER))).scalars().all()
        )
        if existing:
            print(f"StudyBuddy agents already imported ({len(existing)} found). Use --reset to reseed.")
            return

        await ensure_enriched_view(session)

        scope_skill = Skill(
            name="scope_handoff", instruction_text=SCOPE_HANDOFF, created_by=SEED_MARKER
        )
        session.add(scope_skill)

        search_kb_tool = Tool(
            name="search_knowledge_base",
            tool_type="retrieval_tool",
            description=(
                "Search the student's entire class knowledge base for passages relevant "
                "to a question or topic, scoped to their grade/subject/book automatically."
            ),
            config={
                "connection_env": "DATABASE_URL",
                "table": "public.book_chunks_enriched",
                "embedding_column": "embedding",
                "text_column": "content",
                "top_k": 6,
                "state_filter_columns": {"class_grade": "grade", "subject": "subject", "book_id": "book_id"},
                "rerank": "mmr",
                "mmr_lambda": 0.5,
            },
            input_schema=SEARCH_KB_INPUT_SCHEMA,
            created_by=SEED_MARKER,
        )
        get_chapter_tool = Tool(
            name="get_chapter_content",
            tool_type="sql_tool",
            description="Fetch every chunk of a chapter directly, in order, bypassing similarity search.",
            config={
                "connection_env": "DATABASE_URL",
                "query_template": (
                    "SELECT content, page_number, chapter_id, section_title "
                    "FROM public.book_chunks WHERE chapter_id = :chapter_id ORDER BY chunk_index"
                ),
            },
            input_schema=GET_CHAPTER_INPUT_SCHEMA,
            created_by=SEED_MARKER,
        )
        image_gen_tool = Tool(
            name="generate_illustration",
            tool_type="image_gen_tool",
            description="Generate a simple educational diagram/illustration and get back a URL to embed in your answer.",
            config={},
            input_schema=GENERATE_ILLUSTRATION_INPUT_SCHEMA,
            created_by=SEED_MARKER,
        )
        session.add_all([search_kb_tool, get_chapter_tool, image_gen_tool])
        await session.flush()

        tools_by_name = {
            "search_knowledge_base": search_kb_tool,
            "get_chapter_content": get_chapter_tool,
            "generate_illustration": image_gen_tool,
        }

        sub_agent_rows: dict[str, Agent] = {}
        for name, spec in SUB_AGENTS.items():
            agent = Agent(
                name=name,
                description=spec["description"],
                base_instruction=spec["instruction"],
                model_config_json=MODEL_CONFIG,
                output_schema=spec["output_schema"],
                output_key=spec["output_key"],
                created_by=SEED_MARKER,
            )
            session.add(agent)
            await session.flush()

            session.add(AgentSkill(agent_id=agent.id, skill_id=scope_skill.id, attach_order=0))
            for tool_name in spec["tools"]:
                session.add(AgentTool(agent_id=agent.id, tool_id=tools_by_name[tool_name].id))

            sub_agent_rows[name] = agent

        await session.flush()

        # Publish each sub-agent first — the orchestrator's own published
        # snapshot needs each sub-agent to already have a version to build from.
        for name, agent in sub_agent_rows.items():
            spec = SUB_AGENTS[name]
            tools = [tools_by_name[t] for t in spec["tools"]]
            snapshot = _publish_snapshot(agent, tools, [(scope_skill, 0)], [])
            session.add(AgentVersion(agent_id=agent.id, version=1, snapshot=snapshot, published_by=SEED_MARKER))
            agent.status = "published"
            agent.current_version = 1
            session.add(
                ConfigAuditLog(
                    entity_type="agent", entity_id=agent.id, action="publish", actor=SEED_MARKER, diff={"version": 1}
                )
            )

        orchestrator = Agent(
            name="orchestrator",
            description="Classifies student intent and routes to the right StudyBuddy specialist agent.",
            base_instruction=ORCHESTRATOR_INSTRUCTION,
            model_config_json=MODEL_CONFIG,
            created_by=SEED_MARKER,
        )
        session.add(orchestrator)
        await session.flush()

        for name, child in sub_agent_rows.items():
            session.add(AgentSubagent(parent_agent_id=orchestrator.id, child_agent_id=child.id))
        await session.flush()

        snapshot = _publish_snapshot(orchestrator, [], [], list(sub_agent_rows.values()))
        session.add(
            AgentVersion(agent_id=orchestrator.id, version=1, snapshot=snapshot, published_by=SEED_MARKER)
        )
        orchestrator.status = "published"
        orchestrator.current_version = 1
        session.add(
            ConfigAuditLog(
                entity_type="agent",
                entity_id=orchestrator.id,
                action="publish",
                actor=SEED_MARKER,
                diff={"version": 1},
            )
        )

        await session.commit()
        print(f"Created and published 1 skill, 3 tools, {len(sub_agent_rows)} sub-agents, and 1 orchestrator.")
        print(f"Orchestrator agent id: {orchestrator.id}")


if __name__ == "__main__":
    asyncio.run(main())
