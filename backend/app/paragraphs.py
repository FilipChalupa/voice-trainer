"""Longer connected texts to read: a paragraph is queued sentence by sentence, in order, so the intonation of a
story or an explanation ends up in the recordings too (the corpus sentences are short and unrelated).

The texts are original and free to use. Own texts can be pasted as custom sentences in the studio.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from . import prompts
from .config import load_settings
from .recordings import load_index
from .voices import require_voice

router = APIRouter(prefix="/api", tags=["paragraphs"])

BUILTIN: dict[str, list[dict[str, str]]] = {
    "cs": [
        {
            "id": "rano",
            "title": "Ráno v domě",
            "text": "Dobré ráno. Venku je dvanáct stupňů a během dne se má vyjasnit. Kávovar je zapnutý a voda v konvici bude hotová za dvě minuty. Dnes máte v kalendáři tři schůzky, první začíná v devět třicet. Mám vám přečíst zprávy, nebo raději pustit hudbu? Nezapomeňte, že v poledne přijde kurýr s balíkem.",
        },
        {
            "id": "vecer",
            "title": "Večer a odchod z domu",
            "text": "Zamykám dům. Všechna okna jsou zavřená, jen v ložnici zůstalo pootevřené. Topení jsem stáhl na osmnáct stupňů a světla v přízemí zhasla. Pračka doprala před chvílí, prádlo můžete pověsit až ráno. Chcete, abych zapnul alarm hned, nebo až za deset minut? Dobrou noc a hezké sny.",
        },
        {
            "id": "pocasi",
            "title": "Předpověď počasí",
            "text": "Dnes bude převážně oblačno, odpoledne místy přeháňky. Nejvyšší teploty vystoupí na sedmnáct až dvacet stupňů. Vítr bude slabý, jihozápadní, kolem tří metrů za sekundu. V noci se ochladí na osm stupňů a nad ránem může být mlha. Zítra už čekáme slunečno a teplo. O víkendu se ale opět přiblíží studená fronta.",
        },
        {
            "id": "recept",
            "title": "Recept na polévku",
            "text": "Nejdřív si nakrájejte cibuli a osmahněte ji na másle dozlatova. Přidejte tři mrkve, dva brambory a kousek celeru. Zalijte litrem vývaru a vařte dvacet minut, dokud zelenina nezměkne. Potom polévku rozmixujte a dochuťte solí, pepřem a špetkou muškátového oříšku. Podávejte s opečeným chlebem. Kdo má rád, může přidat lžíci smetany.",
        },
        {
            "id": "vylet",
            "title": "Cesta na výlet",
            "text": "Vlak odjíždí v osm patnáct z druhého nástupiště. Cesta trvá hodinu a čtyřicet minut, přestupovat nemusíme. Na místě si půjčíme kola a pojedeme podél řeky až k rozhledně. Vezměte si pláštěnku, odpoledne může sprchnout. Oběd máme zamluvený ve dvanáct v hospodě u přívozu. Kdyby se někdo ztratil, sejdeme se u kostela.",
        },
        {
            "id": "pribeh",
            "title": "Krátký příběh",
            "text": "Když se Marek vrátil domů, bylo už úplně tma. Na stole ležel vzkaz a vedle něj klíče, které celý den hledal. Zasmál se, protože přesně tam je ráno položil. Za oknem zaštěkal pes a někde v dálce projela tramvaj. Uvařil si čaj, sedl si ke stolu a začal psát dopis. Nevěděl ještě, komu ho pošle.",
        },
        {
            "id": "vysvetleni",
            "title": "Jak funguje termostat",
            "text": "Termostat měří teplotu v místnosti a porovnává ji s tou, kterou jste nastavili. Když je chladněji, sepne kotel nebo otevře ventil radiátoru. Jakmile se teplota vyrovná, topení zase vypne. Chytrý termostat navíc umí rozvrh: ráno přitopí, přes den šetří a večer opět zahřeje. Můžete ho ovládat i z telefonu, třeba cestou z práce. Jedna otázka na závěr: víte, kolik stupňů máte nastaveno teď?",
        },
        {
            "id": "rozhovor",
            "title": "Rozhovor v kuchyni",
            "text": "Kde jsou nůžky? Podívej se do horní zásuvky vedle sporáku. Tam nejsou, už jsem hledal dvakrát. Tak zkus polici nad ledničkou, včera jsem je tam viděl. Aha, máš pravdu, díky! Příště je dej zpátky, ať je nehledáme každý den.",
        },
        {
            "id": "cisla",
            "title": "Čísla a časy",
            "text": "Teplota v obýváku je dvacet jedna celá pět stupně. Dnes jste ušli osm tisíc čtyři sta kroků. Do konce nabíjení auta zbývá jedna hodina a dvacet minut. Elektroměr ukazuje spotřebu tři celé dvě kilowatthodiny. Časovač na troubu je nastavený na patnáct minut. Poslední zálivka květin proběhla před třemi dny.",
        },
        {
            "id": "pohadka",
            "title": "Pohádka na dobrou noc",
            "text": "Za sedmero horami stál malý mlýn, ve kterém bydlel mlynář se svou dcerou Aničkou. Každé ráno vstávala první a krmila slepice, kachny a starého osla. Jednoho dne našla u řeky lesklý kámen, který v noci svítil jako hvězda. Když ho vzala do ruky, uslyšela tichý hlas. Kdo mě najde, tomu splním jedno přání. Anička se zamyslela a přála si, aby už nikdo v celém kraji neměl hlad.",
        },
    ],
    "en": [
        {
            "id": "morning",
            "title": "Morning at home",
            "text": "Good morning. It is twelve degrees outside and the sky should clear up during the day. The coffee machine is on and the kettle will be ready in two minutes. You have three meetings in your calendar today, the first one starts at half past nine. Shall I read the news, or would you rather have some music? Do not forget that a courier is bringing a parcel at noon.",
        },
        {
            "id": "evening",
            "title": "Evening and leaving the house",
            "text": "I am locking the house. All windows are closed, only the bedroom one is left ajar. I turned the heating down to eighteen degrees and the lights downstairs are off. The washing machine finished a moment ago, you can hang the laundry in the morning. Do you want the alarm armed right now, or in ten minutes? Good night and sweet dreams.",
        },
        {
            "id": "weather",
            "title": "Weather forecast",
            "text": "Today will be mostly cloudy with scattered showers in the afternoon. Highs will reach seventeen to twenty degrees. The wind will be light, from the southwest, around three metres per second. Tonight it cools down to eight degrees and there may be fog before dawn. Tomorrow we expect sunshine and warmth. At the weekend, however, a cold front is coming back.",
        },
        {
            "id": "recipe",
            "title": "A soup recipe",
            "text": "First chop an onion and fry it in butter until golden. Add three carrots, two potatoes and a piece of celeriac. Pour in a litre of stock and cook for twenty minutes, until the vegetables are soft. Then blend the soup and season it with salt, pepper and a pinch of nutmeg. Serve with toasted bread. Those who like it can add a spoon of cream.",
        },
        {
            "id": "trip",
            "title": "A day trip",
            "text": "The train leaves at a quarter past eight from platform two. The journey takes an hour and forty minutes, no change needed. There we rent bikes and ride along the river up to the lookout tower. Take a raincoat, it may drizzle in the afternoon. Lunch is booked for twelve at the pub by the ferry. If anyone gets lost, we meet at the church.",
        },
        {
            "id": "story",
            "title": "A short story",
            "text": "When Mark came home it was already completely dark. A note lay on the table and next to it the keys he had been looking for all day. He laughed, because that was exactly where he had put them in the morning. A dog barked outside and somewhere far away a tram went by. He made himself a tea, sat down at the table and began to write a letter. He did not yet know whom he would send it to.",
        },
        {
            "id": "explainer",
            "title": "How a thermostat works",
            "text": "A thermostat measures the room temperature and compares it with the one you set. When it is colder, it switches on the boiler or opens the radiator valve. As soon as the temperature matches, the heating goes off again. A smart thermostat also keeps a schedule: it warms up in the morning, saves during the day and heats again in the evening. You can control it from your phone, for example on the way home from work. One question to finish: do you know how many degrees you have set right now?",
        },
        {
            "id": "dialogue",
            "title": "A kitchen conversation",
            "text": "Where are the scissors? Look in the top drawer next to the cooker. They are not there, I have checked twice already. Then try the shelf above the fridge, I saw them there yesterday. Oh, you are right, thanks! Next time put them back, so we do not hunt for them every day.",
        },
        {
            "id": "numbers",
            "title": "Numbers and times",
            "text": "The living room temperature is twenty one point five degrees. You have walked eight thousand four hundred steps today. One hour and twenty minutes remain until the car is charged. The meter shows a consumption of three point two kilowatt hours. The oven timer is set to fifteen minutes. The plants were last watered three days ago.",
        },
        {
            "id": "bedtime",
            "title": "A bedtime story",
            "text": "Beyond seven mountains stood a small mill where a miller lived with his daughter Annie. Every morning she was the first to get up and feed the hens, the ducks and the old donkey. One day she found a shiny stone by the river that glowed at night like a star. When she took it in her hand, she heard a quiet voice. Whoever finds me shall have one wish. Annie thought for a while and wished that nobody in the whole land would ever be hungry again.",
        },
    ],
}


def _sentences(text: str) -> list[str]:
    return prompts.split_sentences(text)


@router.get("/paragraphs")
def get_paragraphs() -> dict[str, Any]:
    voice = require_voice()
    language = load_settings(voice)["language"]
    recorded = {e.get("prompt_id") for e in load_index(voice).values()}
    items = []
    for p in BUILTIN.get(language, []):
        sentences = _sentences(p["text"])
        done = sum(1 for s in sentences if prompts.prompt_id(s) in recorded)
        items.append({"id": p["id"], "title": p["title"], "sentences": len(sentences), "recorded": done, "preview": sentences[0]})
    return {"items": items}


@router.post("/paragraphs/{pid}/queue")
def queue_paragraph(pid: str) -> dict[str, Any]:
    voice = require_voice()
    language = load_settings(voice)["language"]
    paragraph = next((p for p in BUILTIN.get(language, []) if p["id"] == pid), None)
    if paragraph is None:
        raise HTTPException(404, {"code": "not_found", "message": "Unknown paragraph"})
    added = prompts.add_custom(voice, paragraph["text"])
    return {"added": added, "sentences": len(_sentences(paragraph["text"]))}
