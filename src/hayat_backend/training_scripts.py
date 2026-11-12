"""Verbatim scenario replies from the "Hayat Enhanced Training document" (S1 to S17).

When a scenario applies, Hayat says exactly what the document says, so the wording never
drifts. A scenario that comes up again in the same chat gets a short variant instead of the
same paragraph twice. Only English is scripted; other languages use the model, guided by the
same intent.

S1 (the first message) lives in chat_service.greeting() because it depends on the time of day.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Script:
    key: str
    text: str
    # Shorter replies used when the same scenario comes up again in the chat.
    variants: tuple[str, ...] = ()
    # Next steps that follow from this reply (tapped, not typed).
    chips: tuple[str, ...] = ()
    # Whether the planned next question may follow the script (flow keeps going).
    then_ask: bool = False
    marker: str = field(default="", compare=False)


SCRIPTS: dict[str, Script] = {
    "S2": Script(
        "S2",
        "It's lovely to meet you. What would you like me to call you? A first name is perfect, "
        "and no worries if you'd rather not say.",
        chips=("I'd rather not say",),
    ),
    "S3": Script(
        "S3",
        "Thank you for trusting me with that, it really matters. The specifics of your health are "
        "best looked at privately by one of our medical advisors, so I'll keep them out of your "
        "enquiry summary.",
        variants=(
            "Thank you for telling me, and I'll keep that private for our medical advisors.",
            "Of course. That stays out of your enquiry summary, and a medical advisor can look at "
            "it with you.",
        ),
        then_ask=True,
    ),
    "S4": Script(
        "S4",
        "I'm not able to interpret reports or symptoms, and I wouldn't want to guess about "
        "something this important. A medical advisor can go through it with you in your free "
        "consultation, and you can share documents securely once your free account is set up.",
        variants=(
            "That one is best left to a medical advisor in your free consultation, so I wouldn't "
            "want to guess.",
            "A medical advisor can explain that properly in your free consultation.",
        ),
        then_ask=True,
    ),
    "S5": Script(
        "S5",
        "That sounds wonderful, and a break like this can really make a difference. Is there a "
        "particular feeling you'd love to come home with, like more energy, calm or a fresh start?",
        chips=("More energy", "Calm", "A fresh start"),
    ),
    "S6": Script(
        "S6",
        "The best next step is a free consultation with one of our medical advisors, who can talk "
        "through your options with you. To arrange it, you'll create a free trawellcare account, "
        "which also keeps your details and any documents safe. Shall I take you to the signup and "
        "login page now? 😊",
        chips=("Yes, take me to signup", "Not right now"),
    ),
    "S7": Script(
        "S7",
        "I'd love for our wellness curator to shape this with you on a free call. You'll just need "
        "a free trawellcare account to book it, and you can choose how you'd like us to stay in "
        "touch. Would you like me to take you to the signup and login page?",
        chips=("Yes, take me to signup", "Not right now"),
    ),
    "S8": Script(
        "S8",
        "Of course, there's no pressure at all. The signup and login page is always at the top of "
        "the page whenever you're ready, and I'm here if any questions come up.",
        chips=("I have a question", "Tell me about the programmes"),
    ),
    "S9": Script(
        "S9",
        "Thank you for wanting to share that. To keep your details safe I can't take contact "
        "information here in the chat. When you create your free account you can add it securely "
        "and choose exactly how we reach you.",
        variants=(
            "I can't take contact details in the chat, but you can add them securely when you "
            "create your free account.",
        ),
        then_ask=True,
    ),
    "S10": Script(
        "S10",
        "Absolutely. The quickest route is to book your free consultation after you log in or "
        "create your account. If you'd prefer to reach our team directly, you can use {support}.",
        variants=(
            "The quickest route is still to book your free consultation once you log in or create "
            "your account.",
        ),
    ),
    "S11": Script(
        "S11",
        "Understood, and thank you for telling me. I'll pass that on straight away so we stop "
        "contacting you, and you can also change your choices anytime in your account settings. "
        "For a request to delete your information, I'll point you to our privacy request page so "
        "the right team can take care of it.",
    ),
    "S12": Script(
        "S12",
        "We can do that. When you create your free account you'll be able to choose WhatsApp, "
        "email or phone, and we'll only reach out in the ways you say yes to.",
        variants=(
            "Yes, you'll choose WhatsApp, email or phone when you create your free account.",
        ),
        then_ask=True,
    ),
    "S13": Script(
        "S13",
        "This sounds like it may need urgent attention right now, and I'm not able to help with "
        "emergencies. Please contact your local emergency number straight away, or go to the "
        "nearest emergency room. I'll be here whenever you're ready to plan.",
    ),
    "S14": Script(
        "S14",
        "Our services are for adults, so I'm not able to continue this enquiry here. If you're "
        "planning something with a parent or guardian, they are welcome to create an account and "
        "speak with our team.",
    ),
    "S15": Script(
        "S15",
        "Please don't share that here, the chat isn't the place for it. Let's carry on, and any "
        "secure steps happen after you log in.",
        then_ask=True,
    ),
    "S16": Script(
        "S16",
        "I'm Hayat, trawellcare's AI assistant, and the team behind me are real people who'll be "
        "glad to speak with you in your free consultation.",
        variants=("I'm an AI assistant, and the team behind me are real people.",),
        chips=("How does trawellcare work?",),
        then_ask=True,
    ),
    "S17": Script(
        "S17",
        "That's a lovely question! 😊 At trawellcare we make it much easier to find and access "
        "healthcare and wellness experiences across borders. It starts with understanding what "
        "you're looking for, whether that's a medical treatment, a restful retreat, a longevity "
        "programme or a fitness experience. Our matching system and our team then help identify "
        "options, providers and destinations that fit your needs, preferences and budget. Once "
        "you've found what feels right, we help coordinate your journey, including consultations, "
        "bookings, visas, flights, accommodation, transfers and concierge support, and you're "
        "supported throughout. We also stay in touch afterwards with aftercare and ongoing "
        "wellness support, in the ways you choose. ❤ Would you like to tell me a little about "
        "what you have in mind?",
        variants=(
            "In short, we help you find the right care or wellness experience, coordinate the "
            "journey, and stay in touch afterwards. What would you like to know more about?",
        ),
        chips=("I'm interested in medical treatment", "I'm interested in a wellness retreat"),
    ),
}


def _marker(script: Script) -> str:
    return re.sub(r"\W+", " ", script.text[:48]).strip().lower()


def times_used(key: str, assistant_messages: list[str]) -> int:
    """How often the verbatim reply or one of its variants was already said in this chat."""
    script = SCRIPTS[key]
    markers = [_marker(script), *[re.sub(r"\W+", " ", v[:40]).strip().lower() for v in script.variants]]
    count = 0
    for message in assistant_messages:
        normal = re.sub(r"\W+", " ", message).strip().lower()
        if any(m and m in normal for m in markers):
            count += 1
    return count


def script_reply(key: str, assistant_messages: list[str], support: str | None = None) -> Script | None:
    """The reply for a scenario: verbatim the first time, a short variant after that."""
    script = SCRIPTS.get(key)
    if script is None:
        return None
    used = times_used(key, assistant_messages)
    text = script.text
    if used and script.variants:
        text = script.variants[(used - 1) % len(script.variants)]
    if "{support}" in text:
        if support:
            text = text.format(support=support)
        else:  # the support channel is still to be confirmed: leave that sentence out
            text = text.split(" If you'd prefer")[0]
    return Script(key, text, script.variants, script.chips, script.then_ask)


def lower_brand(text: Any) -> Any:
    """trawellcare is always written in lower case."""
    if not isinstance(text, str):
        return text
    return re.sub(r"(?i)\btrawell\s?care\b", "trawellcare", text)
