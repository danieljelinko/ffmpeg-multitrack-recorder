# Ruler: AI Coding Assistant Rules Management

## Overview

Ruler is a tool that centralizes and manages AI coding assistant instructions across multiple platforms and repositories. This project uses Ruler to maintain a **single source of truth** for coding conventions and project-specific guidelines.

## How Ruler Works

1. **Centralized Rules**: All coding rules and instructions are stored in `.ruler_org/` directory
2. **Distribution**: Rules are distributed to individual repositories via **hard links** (required for Ruler to function)
3. **Configuration**: Each repository has a `.ruler/` directory containing:
   - Hard links to applicable rule files from `.ruler_org/`
   - `AGENTS.md` - specifies which rules apply
   - `ruler.toml` - configuration for agents and MCP servers
4. **Application**: Run `ruler apply` in each repository to generate agent-specific config files

## Hard Link Requirement

**Important**: Ruler requires hard links, not symbolic links, to function correctly. This ensures that:
- Rule updates in `.ruler_org/` immediately propagate to all repositories
- File integrity is maintained across the project structure
- Ruler can properly track and manage rule dependencies

## Single Source of Truth

- **Master Location**: `/home/helinko/Work/guess-class/.ruler_org/`
- **Rule Files**: All `.md` rule files live here
- **Configuration**: `ruler.toml` and `AGENTS.md` are maintained here
- **Distribution**: Hard links create the same files in repository `.ruler/` directories

## Automation

Rules are distributed via the `sync-ruler-rules.sh` automation script which:
1. Creates `.ruler/` directories in target repositories
2. Creates hard links for applicable rules based on repository type
3. Runs `ruler apply` to generate agent configs
4. Tests that ruler functionality works correctly

### Manual Trigger

The automation is triggered manually but agents can request rule updates by asking to:
1. Run the `sync-ruler-rules.sh` script
2. Execute `ruler apply` in specific repositories  
3. Verify rule distribution and functionality

## Repository Types

- **Universal Rules**: Applied to all repositories (coding style, package management, ruler docs)
- **UI Projects**: Get additional FastHTML/HTMX/MonsterUI rules
- **Notebook Projects**: Get nbdev structure rules (except guess-class-core which has special nbdev rules)

This system ensures consistent coding standards and AI assistant behavior across the entire guess-class ecosystem.
