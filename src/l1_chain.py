"""Lesson 1 - a LangChain chain. No graph at all.

A chain is one direction: prompt -> model -> text. The `|` operator wires the steps.
Run:  uv run python src/l1_chain.py
"""

from langchain_core.prompts import ChatPromptTemplate

from common import llm, load_claim

prompt = ChatPromptTemplate.from_messages([
    ("system", "You explain US medical billing to beginners. Answer in 3 sentences, no lists."),
    ("human", "Procedure code {code} ({desc}) was billed at ${charge} to {payer}, "
              "whose contracted rate is ${allowed}. What does this code cover, and why "
              "does the paid amount differ from the charge?"),
])

chain = prompt | llm()  # <- the whole "chain" is this one line

if __name__ == "__main__":
    claim = load_claim(1001)
    answer = chain.invoke({
        "code": claim["code"],
        "desc": claim["short_desc"],
        "charge": claim["charge_amount"],
        "payer": claim["payer_name"],
        "allowed": claim["allowed_amount"],
    })
    print(answer.content)

# What to notice:
#   * No state, no branching, no retries. Input goes in, text comes out.
#   * If you needed "retry when the answer is bad" or "ask a human first",
#     there is nowhere to put it. That is the gap lesson 2 fills.
