# Progressive Disclosure Specification

## Problem

Currently, `tektonit/prompts.py` loads ALL agent instructions into EVERY LLM call. This wastes tokens and increases latency.

**Current approach**:
```python
# EVERY generation call loads ~10,000 tokens of agent instructions
prompt = BATS_SYSTEM_PROMPT  # Full agent markdown body
llm.generate(system=prompt, user=script)
```

**Token cost per generation**: ~10,000 system + ~5,000 script = 15,000 tokens

For a catalog with 50 resources, that's 750,000 tokens of redundant system prompts.

## Solution: 3-Level Progressive Disclosure

Load only what you need, when you need it.

### Level 1: Metadata Only (~100 tokens)

**When**: Initial routing decision — which agent should handle this?

**Contains**:
- name
- description (first paragraph only)
- tags
- TRIGGER conditions
- DO NOT TRIGGER conditions

**Example**:
```python
AGENT_METADATA = {
    "stepaction-test-generator": {
        "name": "stepaction-test-generator",
        "description": "Generate BATS/pytest tests for Tekton StepAction single-script resources",
        "tags": ["testing", "stepaction", "bats", "pytest"],
        "trigger": "user requests test generation for Tekton StepAction YAML",
        "do_not_trigger": "multi-step Tasks or Pipelines"
    }
}
```

**Decision flow**:
```python
# Load only metadata (100 tokens)
agent = select_agent_for_resource(resource_type, AGENT_METADATA)

# Now load full prompt for that one agent
system_prompt = load_agent_prompt(agent.name)
```

### Level 2: Full Agent Body (<5,000 tokens)

**When**: Agent has been selected and is generating tests

**Contains**:
- Complete agent instructions
- Generation protocol
- Decision framework
- Examples (inline)
- Self-check checklists

**Does NOT include**:
- External documentation URLs (unless requested)
- Long reference implementations
- Historical context (loaded from state.db if needed)

### Level 3: Resources (loaded on-demand)

**When**: Agent explicitly requests "show me BATS documentation" or encounters an error

**Contains**:
- External documentation excerpts
- Reference test implementations
- Advanced examples
- Troubleshooting guides

## Implementation Plan

### Phase 1: Refactor prompts.py Structure

**Current**:
```python
BATS_SYSTEM_PROMPT = """...(10,000 tokens)..."""
```

**New**:
```python
AGENT_METADATA = {
    "stepaction": {...},
    "task": {...},
    "pipeline": {...}
}

AGENT_PROMPTS = {
    "stepaction": """...(core instructions)...""",
    "task": """...(core instructions)...""",
    "pipeline": """...(core instructions)..."""
}

AGENT_RESOURCES = {
    "stepaction": {
        "bats_docs": """...(external docs)...""",
        "examples": """...(reference tests)..."""
    }
}
```

### Phase 2: Update build_prompts_from_agents.py

Extract frontmatter separately from body:

```python
def extract_frontmatter(md_content):
    """Extract YAML frontmatter as metadata."""
    if md_content.startswith('---'):
        parts = md_content.split('---', 2)
        frontmatter = yaml.safe_load(parts[1])
        body = parts[2].strip()
        return frontmatter, body
    return {}, md_content

def extract_resources(md_content):
    """Extract resources section separately."""
    # Look for ## Resources heading
    # Extract URLs and descriptions
    # Return as structured dict
```

### Phase 3: Update llm.py to Use Progressive Loading

```python
class LLMProvider:
    def generate_test(self, resource, script, lessons=[]):
        # Level 1: Select agent based on metadata
        agent = self._select_agent(resource.kind)

        # Level 2: Load full prompt for selected agent
        system_prompt = self._build_system_prompt(agent, lessons)

        # Level 3: Resources loaded only if LLM requests them
        # (future enhancement with tool calling)

        response = self.client.generate(
            system=system_prompt,
            user=script
        )
        return response

    def _select_agent(self, resource_kind):
        """Use metadata only to route to correct agent."""
        metadata = AGENT_METADATA.get(resource_kind)
        return metadata['name']

    def _build_system_prompt(self, agent_name, lessons):
        """Build prompt with agent instructions + lessons."""
        base_prompt = AGENT_PROMPTS[agent_name]

        if lessons:
            lessons_section = "\\n".join([f"- {l}" for l in lessons])
            prompt = f"{base_prompt}\\n\\nLessons from past failures:\\n{lessons_section}"
        else:
            prompt = base_prompt

        return prompt
```

### Phase 4: Token Savings Calculation

**Before (current)**:
- System prompt: 10,000 tokens (full agent + all instructions)
- User prompt: 5,000 tokens (script)
- **Total per generation: 15,000 tokens**

**After (progressive disclosure)**:
- Metadata (routing): 100 tokens (only loaded once per batch)
- System prompt: 3,000 tokens (selected agent only, no resources)
- User prompt: 5,000 tokens (script)
- **Total per generation: 8,000 tokens**

**Savings**: 47% reduction in tokens per generation

For 50 resources:
- Before: 750,000 tokens
- After: 400,000 tokens
- **Savings: 350,000 tokens (~$1.75 at Gemini pricing)**

## Future Enhancement: Tool Calling for Level 3

When the agent needs documentation:

```python
# Agent can call a tool during generation
tools = [
    {
        "name": "get_resource",
        "description": "Retrieve BATS documentation or examples",
        "parameters": {
            "resource_name": "bats_docs | examples | troubleshooting"
        }
    }
]

# LLM calls tool
response = llm.generate(system=prompt, user=script, tools=tools)

if response.tool_calls:
    for call in response.tool_calls:
        if call.name == "get_resource":
            resource = AGENT_RESOURCES[agent][call.args["resource_name"]]
            # Inject resource into next LLM call
```

## Migration Strategy

### Step 1: Create parallel system
- Keep existing `BATS_SYSTEM_PROMPT` for backward compatibility
- Add new `AGENT_METADATA`, `AGENT_PROMPTS` structures
- Add feature flag: `USE_PROGRESSIVE_DISCLOSURE=False`

### Step 2: Test new system
- Run generation with both systems
- Compare output quality
- Measure token usage
- Verify no regressions

### Step 3: Gradual rollout
- Enable progressive disclosure for simple resources first
- Monitor quality metrics
- Expand to complex resources
- Eventually deprecate old system

### Step 4: Cleanup
- Remove backward compatibility code
- Update all documentation
- Simplify build script

## Risks and Mitigations

**Risk**: Reduced context might hurt quality
- **Mitigation**: Keep essential instructions in Level 2, only defer reference material

**Risk**: Agent selection logic might be wrong
- **Mitigation**: Comprehensive metadata in Level 1, fallback to multi-agent approach

**Risk**: Breaking changes in existing deployments
- **Mitigation**: Feature flag, gradual rollout, extensive testing

## Success Metrics

- [ ] 40%+ reduction in tokens per generation
- [ ] No quality degradation (test pass rate unchanged)
- [ ] No increase in fix attempts needed
- [ ] Faster LLM response times (less to process)
- [ ] Lower API costs

## References

- Agent Skills spec: https://agentskills.io/
- Progressive disclosure pattern: https://www.nngroup.com/articles/progressive-disclosure/
- Context window optimization: https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/long-context-tips
