---
title: ResidueCheck
emoji: 🍊
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Check a spray log against EU pesticide residue limits
---

# ResidueCheck

Checks a farm's spray log against EU maximum residue limits before harvest, using Morocco's official ONSSA
register and the EU Pesticides Database. Verdicts come from fixed rules with the regulation linked.

This Space runs without API keys: the AI steps (Nemotron on Nebius Token Factory, Tavily web search) are replayed
from recorded runs for the demo lots, and any other input is checked by the fixed rules only. Every result says
which engine produced it.

Source, evaluation and method: https://github.com/BriceZemba/residuecheck
