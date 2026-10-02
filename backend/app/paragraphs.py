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
        {
            "id": "nakup",
            "title": "Nákupní seznam a plán dne",
            "text": "Na nákupním seznamu máte mléko, chléb, vejce, máslo a dvě kila brambor. Přidal jsem ještě kávu, protože včera došla. Obchod zavírá v osm večer, dnes je otevřeno déle. Odpoledne ve tři máte zubaře, cesta trvá dvacet minut. Do kalendáře jsem zapsal také narozeniny tety Marie, jsou příští úterý. Prádlo v sušičce bude hotové za půl hodiny. Chcete, abych vám připomněl, až bude? Teplota v dětském pokoji klesla na devatenáct stupňů, mám přitopit? A ještě jedna věc: baterie v senzoru na balkoně je skoro vybitá.",
        },
        {
            "id": "tyden",
            "title": "Týdenní předpověď",
            "text": "V pondělí bude polojasno s teplotami kolem patnácti stupňů. Úterý přinese déšť, místy i bouřky, a silný vítr od západu. Ve středu se vyjasní, ale ráno hrozí přízemní mrazíky. Čtvrtek a pátek budou slunečné, odpoledne až dvacet dva stupňů. O víkendu se oteplí ještě víc, sobota bude nejteplejší den týdne. Neděle večer se od severu přiblíží studená fronta. Kdy plánujete výlet? Doporučil bych čtvrtek nebo sobotu, v úterý si raději vezměte deštník.",
        },
        {
            "id": "pribeh2",
            "title": "Příběh z vlaku",
            "text": "Vlak se rozjel s mírným zpožděním a Petra si konečně sedla k oknu. Venku se míhaly pole, remízky a občas nějaká vesnice s kostelem. Naproti ní seděl starší pán s novinami a každou chvíli něco zamručel. V Kolíně přistoupila paní se dvěma dětmi a kufrem, který se nevešel do police. Petra jim pomohla a dala se s nimi do řeči. Ukázalo se, že jedou na stejnou svatbu jako ona. Jaká je pravděpodobnost, že se tohle stane? Smáli se tomu až do Pardubic. Když vystupovali, pán s novinami se poprvé usmál a popřál jim hezkou oslavu.",
        },
        {
            "id": "navod",
            "title": "Návod k zavařování",
            "text": "Sklenice nejdřív důkladně umyjte a nechte je vysušit dnem vzhůru. Ovoce omyjte, odpeckujte a nakrájejte na stejně velké kousky. Na kilogram ovoce počítejte zhruba čtyři sta gramů cukru. Směs přiveďte k varu a za stálého míchání vařte deset minut. Horkou marmeládu plňte až po okraj a sklenice ihned uzavřete. Potom je otočte víčkem dolů a nechte je deset minut stát. Víčka by se měla po vychladnutí prohnout dovnitř. Pokud některé víčko cvaká, sklenici uložte do lednice a snězte ji první. Takhle vydrží zavařenina klidně rok.",
        },
        {
            "id": "sport",
            "title": "Sportovní zpráva",
            "text": "Domácí vstoupili do zápasu aktivně a už v páté minutě vedli jednu nula. Hosté vyrovnali těsně před přestávkou z pokutového kopu. Druhý poločas začal opatrně, obě mužstva si dávala pozor na chyby. Rozhodující moment přišel v osmdesáté třetí minutě, kdy střídající útočník zakončil rychlý protiútok. Konečný výsledek dvě jedna znamená pro domácí první výhru po čtyřech zápasech. Trenér po utkání chválil obranu i diváky, kterých přišlo přes šest tisíc. Příští sobotu čeká tým zápas venku, výkop je v půl šesté.",
        },
        {
            "id": "priroda",
            "title": "Procházka lesem",
            "text": "Ráno bylo chladné a nad loukou se ještě držela mlha. Cesta vedla podél potoka, který po nočním dešti hlasitě šuměl. Mezi stromy jsme zahlédli srnku, ale než jsem stačil vytáhnout telefon, byla pryč. Na pasece kvetly vlčí máky a nad nimi kroužil káně. Pod starým bukem jsme našli první hříbky letošního roku. Děti počítaly letokruhy na pařezu a došly k číslu osmdesát sedm. Cestou zpátky se vyjasnilo a z rozhledny byly vidět Krkonoše. Domů jsme dorazili unavení, špinaví a spokojení.",
        },
        {
            "id": "historie",
            "title": "Z historie města",
            "text": "Město bylo založeno ve třináctém století na křižovatce obchodních cest. Původní dřevěné hradby nahradily kamenné až o dvě stě let později. Náměstí si dodnes zachovalo středověký půdorys, i když většina domů má barokní fasády. Radniční věž měří padesát dva metrů a vede na ni sto dvacet schodů. V roce tisíc osm set osmdesát šest sem dorazila železnice a s ní první továrny. Dnes tu žije přibližně dvacet tisíc obyvatel. Nejstarší dochovaná listina je uložena v okresním archivu. Prohlídka s průvodcem začíná každý den v deset a ve dvě hodiny.",
        },
        {
            "id": "asistent",
            "title": "Rozhovor s asistentem",
            "text": "Jaké bude dnes počasí? Dopoledne polojasno, odpoledne přeháňky, nejvyšší teplota šestnáct stupňů. Nastav budík na půl sedmé. Budík je nastavený na šest třicet ráno. Kolik je hodin? Je čtvrt na osm. Přidej na seznam mouku a cukr. Přidáno, na seznamu máte teď šest položek. Zapni světlo v kuchyni na padesát procent. Hotovo. Jak dlouho trvá cesta do práce? Při současném provozu dvacet pět minut. Děkuji. Rádo se stalo, hezký den.",
        },
        {
            "id": "dopis",
            "title": "Dopis kamarádce",
            "text": "Milá Kláro, konečně jsem si našla chvíli, abych ti napsala. Stěhování máme za sebou, i když krabice ještě stojí v chodbě. Nový byt je menší, ale má balkon s výhledem na řeku a to mi dělá velkou radost. Děti si zvykly rychleji než my, už mají kamarády v domě. Práce je zatím stejná, jen cesta trvá o dvacet minut déle. V sobotu bychom vás rádi pozvali na oběd, co vy na to? Dej vědět, jestli vám to vyhovuje, uvařím něco bezlepkového. Moc se na vás těším, pozdravuj Honzu a kluky.",
        },
        {
            "id": "zpravy",
            "title": "Krátké zprávy",
            "text": "Vláda dnes schválila rozpočet na příští rok, výdaje porostou o tři procenta. V Brně otevřeli nový úsek tramvajové trati o délce čtyři kilometry. Astronomové objevili planetu, která obíhá dvě hvězdy najednou. Ceny potravin v dubnu mírně klesly, nejvíc zlevnilo máslo. Hokejová reprezentace vyhrála přípravný zápas tři dva v prodloužení. Zítra bude v celé republice oblačno, na horách sněžení. Dálnice u Humpolce je po nehodě průjezdná jedním pruhem. A na závěr: v Praze se narodilo mládě žirafy, váží šedesát pět kilo.",
        },
        {
            "id": "pohadka2",
            "title": "O lišce a vráně",
            "text": "Vrána seděla na větvi a v zobáku držela kus sýra. Pod stromem se zastavila liška a hladově se podívala nahoru. Jak krásné máš peří, zavolala na vránu, a jak chytré oči! Určitě máš i nejkrásnější hlas v celém lese. Vrána se zaradovala, otevřela zobák a zakrákala. Sýr spadl na zem a liška ho chňapla dřív, než dopadl. Příště si pochvalu nejdřív prověř, zasmála se a zmizela v křoví. Vrána od té doby mlčí, kdykoli má v zobáku něco dobrého.",
        },
        {
            "id": "otazky",
            "title": "Otázky a zvolání",
            "text": "Opravdu jsi to udělal sám? To snad není možné! Kde jsi nechal klíče od auta? Pojď sem, rychle! Kolik to stálo, dvě stě, nebo tři sta? Nevěřím ti ani slovo. Proč jsi mi to neřekl dřív? Pozor, schod! Mohl bys mi prosím podat tu knihu? Výborně, přesně tohle jsem potřeboval. Jak dlouho ještě budeme čekat? Neboj se, všechno dobře dopadne.",
        },
        {
            "id": "q-asistent-pta",
            "title": "Otázky: asistent se ptá",
            "text": "Mám zhasnout světlo v obýváku? Chcete, abych zamkl vchodové dveře? Mám vám zítra ráno připomenout schůzku? Je v ložnici příliš teplo? Mám stáhnout rolety v celém domě? Přejete si pustit ranní zprávy? Mám zapnout topení v koupelně? Chcete přidat mléko na nákupní seznam? Mám budík nastavit i na sobotu? Slyšíte mě dobře? Mám tu zprávu přečíst ještě jednou? Opravdu chcete vypnout všechna světla?",
        },
        {
            "id": "q-na-asistenta",
            "title": "Otázky: ptám se asistenta",
            "text": "Kolik je teď venku stupňů? Kdy mi jede první ranní autobus? Kde jsem nechal nabíječku od telefonu? Proč svítí kontrolka na pračce? Jak dlouho ještě poběží myčka? Kdo dnes zvonil u dveří? Co mám zítra v kalendáři? Kolik elektřiny jsme spotřebovali tento týden? Kdy naposledy někdo zaléval kytky? Jaká je teplota v dětském pokoji? Které okno zůstalo otevřené? Kam jsem si uložil ten recept na guláš?",
        },
        {
            "id": "q-vyber",
            "title": "Otázky: výběr ze dvou",
            "text": "Chcete čaj, nebo kávu? Pojedeme vlakem, nebo autem? Mám to poslat dnes, nebo až zítra? Zůstaneme doma, nebo půjdeme ven? Dáte si polévku, nebo rovnou hlavní jídlo? Platíte kartou, nebo hotově? Sejdeme se v pět, nebo raději v šest? Mám rozsvítit lampu, nebo stropní světlo? Bude to stačit takhle, nebo mám přidat? Voláš ty jemu, nebo zavolá on tobě? Půjdeme pěšky, nebo počkáme na tramvaj? Chceš to slyšet hned, nebo až po večeři?",
        },
        {
            "id": "q-lekar",
            "title": "Otázky: u lékaře",
            "text": "Dobrý den, co vás k nám přivádí? Už tři dny mě bolí v krku. Máte také teplotu? Večer mívám kolem třiceti osmi. Berete nějaké léky? Jenom kapky proti kašli. Jste na něco alergický? Pokud vím, tak na nic. Kdy jste byl naposledy na prohlídce? Asi před dvěma lety. Můžete se zhluboka nadechnout? Bolí to, když polykáte? Předepíšu vám antibiotika, ano? Přijdete se ukázat za týden?",
        },
        {
            "id": "q-cesta",
            "title": "Otázky: na cestě",
            "text": "Promiňte, jak se dostanu na nádraží? Jděte rovně a u lékárny zahněte doleva. Je to odtud daleko? Pěšky asi deset minut. Jede tam nějaký autobus? Jede, číslo dvanáct, staví hned za rohem. Kde si mohu koupit jízdenku? V trafice, nebo přímo u řidiče. Stihnu ještě vlak v půl čtvrté? Když si pospíšíte, tak určitě. Z kterého nástupiště odjíždí? To vám bohužel nepovím. A nevíte, jestli má zpoždění? Zeptejte se raději u pokladny.",
        },
        {
            "id": "q-proc",
            "title": "Otázky: zvídavé dítě",
            "text": "Proč je nebe modré? Protože vzduch rozptyluje sluneční světlo. A proč je večer červené? Protože světlo letí delší cestou. Kam chodí slunce spát? Nikam, to se jenom otáčí Země. Kdo zhasíná hvězdy? Nikdo, ve dne je jen přesvítí slunce. Jak vysoko létají ptáci? Někteří výš než letadla. Co jedí ryby v zimě? Skoro nic, pod ledem jen odpočívají. Proč musím jít spát, když nejsem unavený? Protože zítra vstáváme brzy. A můžu si ještě chvíli číst?",
        },
        {
            "id": "q-dovetky",
            "title": "Otázky: ujištění a údiv",
            "text": "To je tvoje kolo, že ano? Zamkl jsi dveře, viď? Ty jsi tam vážně šel sám? On to opravdu řekl nahlas? Přijdete zítra, že jo? Tohle má být všechno? Vy jste se už viděli? Ona o tom vůbec nevěděla? Nezapomněl jsi na ty klíče, že ne? Takže se sejdeme v sedm? To myslíš vážně? A to vám nikdo neřekl?",
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
            "text": "Today will be mostly cloudy with scattered showers in the afternoon. Highs will reach seventeen to twenty degrees. The wind will be light, from the southwest, around three meters per second. Tonight it cools down to eight degrees and there may be fog before dawn. Tomorrow we expect sunshine and warmth. At the weekend, however, a cold front is coming back.",
        },
        {
            "id": "recipe",
            "title": "A soup recipe",
            "text": "First chop an onion and fry it in butter until golden. Add three carrots, two potatoes and a piece of celeriac. Pour in a liter of stock and cook for twenty minutes, until the vegetables are soft. Then blend the soup and season it with salt, pepper and a pinch of nutmeg. Serve with toasted bread. Those who like it can add a spoon of cream.",
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
        {
            "id": "shopping",
            "title": "Shopping list and the day's plan",
            "text": "Your shopping list has milk, bread, eggs, butter and two kilos of potatoes. I added coffee too, because it ran out yesterday. The shop closes at eight tonight, it is open longer today. At three in the afternoon you have the dentist, the drive takes twenty minutes. I also put aunt Mary's birthday in the calendar, it is next Tuesday. The laundry in the dryer will be done in half an hour. Do you want a reminder when it is? The temperature in the children's room dropped to nineteen degrees, shall I turn the heating up? One more thing: the battery in the balcony sensor is almost flat.",
        },
        {
            "id": "week",
            "title": "The week's forecast",
            "text": "Monday will be partly cloudy with temperatures around fifteen degrees. Tuesday brings rain, thunderstorms in places and a strong westerly wind. On Wednesday it clears up, but there may be ground frost in the morning. Thursday and Friday will be sunny, up to twenty two degrees in the afternoon. The weekend gets warmer still, Saturday will be the warmest day of the week. On Sunday evening a cold front approaches from the north. When are you planning the trip? I would suggest Thursday or Saturday; on Tuesday, take an umbrella.",
        },
        {
            "id": "train",
            "title": "A story from the train",
            "text": "The train left with a slight delay and Petra finally sat down by the window. Fields, copses and the odd village with a church flashed past outside. Opposite her sat an older gentleman with a newspaper, muttering every now and then. In Colchester a woman with two children got on, with a suitcase that did not fit on the rack. Petra helped them and got talking. It turned out they were going to the same wedding as she was. What are the odds of that? They laughed about it all the way to Ipswich. When they got off, the man with the newspaper smiled for the first time and wished them a lovely party.",
        },
        {
            "id": "jam",
            "title": "How to make jam",
            "text": "First wash the jars thoroughly and let them dry upside down. Wash the fruit, remove the stones and cut it into pieces of the same size. Count roughly four hundred grams of sugar per kilogram of fruit. Bring the mixture to the boil and cook for ten minutes, stirring all the time. Fill the jars with the hot jam right to the brim and close them at once. Then turn them lid down and leave them for ten minutes. The lids should curve inwards as they cool. If a lid clicks, keep that jar in the fridge and eat it first. Made this way, the jam keeps for a year.",
        },
        {
            "id": "match",
            "title": "Sports report",
            "text": "The home side started the match on the front foot and led one nil as early as the fifth minute. The visitors equalized from a penalty just before the break. The second half began cautiously, both teams wary of mistakes. The decisive moment came in the eighty third minute, when a substitute striker finished a quick counter-attack. The final score of two one means the first win in four games for the hosts. After the match the coach praised the defense and the crowd of more than six thousand. Next Saturday the team plays away, kick-off is at half past five.",
        },
        {
            "id": "forest",
            "title": "A walk in the woods",
            "text": "The morning was cold and mist still hung over the meadow. The path ran along a brook that murmured loudly after the night's rain. Between the trees we glimpsed a deer, but it was gone before I could get my phone out. Poppies bloomed in the clearing and a buzzard circled above them. Under the old beech we found the first mushrooms of the year. The children counted the rings on a stump and arrived at eighty seven. On the way back the sky cleared and the hills were visible from the lookout. We got home tired, muddy and content.",
        },
        {
            "id": "history",
            "title": "From the town's history",
            "text": "The town was founded in the thirteenth century at a crossroads of trade routes. The original wooden walls were replaced by stone ones two hundred years later. The square keeps its medieval layout to this day, although most houses have baroque fronts. The town hall tower is fifty two meters high and a hundred and twenty steps lead to the top. In eighteen eighty six the railway arrived, and the first factories with it. Today about twenty thousand people live here. The oldest surviving charter is kept in the district archive. The guided tour starts every day at ten and at two o'clock.",
        },
        {
            "id": "assistant",
            "title": "Talking to the assistant",
            "text": "What is the weather today? Partly cloudy in the morning, showers in the afternoon, a high of sixteen degrees. Set an alarm for half past six. The alarm is set for six thirty in the morning. What time is it? It is a quarter past seven. Add flour and sugar to the list. Added, there are six items on the list now. Turn the kitchen light on at fifty percent. Done. How long is the drive to work? Twenty five minutes in the current traffic. Thank you. You are welcome, have a nice day.",
        },
        {
            "id": "letter",
            "title": "A letter to a friend",
            "text": "Dear Clare, I have finally found a moment to write to you. The move is behind us, although boxes still stand in the hall. The new flat is smaller, but it has a balcony looking over the river and that makes me very happy. The children settled in faster than we did, they already have friends in the building. Work is the same so far, only the commute takes twenty minutes longer. On Saturday we would love to have you over for lunch, what do you say? Let me know if it suits you, I will cook something gluten-free. I am really looking forward to seeing you, give my love to John and the boys.",
        },
        {
            "id": "news",
            "title": "Brief news",
            "text": "The government approved next year's budget today, spending will rise by three percent. A new four kilometer stretch of tram line opened in Manchester. Astronomers discovered a planet that orbits two stars at once. Food prices fell slightly in April, butter dropped the most. The national hockey team won a friendly three two in overtime. Tomorrow will be cloudy across the country, with snow on the hills. The motorway near Leeds is passable in one lane after an accident. And finally: a baby giraffe was born in London, it weighs sixty five kilos.",
        },
        {
            "id": "fox",
            "title": "The fox and the crow",
            "text": "A crow sat on a branch with a piece of cheese in her beak. A fox stopped under the tree and looked up hungrily. What beautiful feathers you have, she called to the crow, and what clever eyes! Surely you have the loveliest voice in the whole forest too. The crow was delighted, opened her beak and cawed. The cheese fell and the fox snapped it up before it hit the ground. Next time, check the praise first, she laughed, and vanished into the bushes. Ever since, the crow keeps quiet whenever she has something tasty in her beak.",
        },
        {
            "id": "questions",
            "title": "Questions and exclamations",
            "text": "Did you really do it yourself? That cannot be true! Where did you leave the car keys? Come here, quickly! How much was it, two hundred or three hundred? I do not believe a word of it. Why did you not tell me sooner? Mind the step! Could you pass me that book, please? Excellent, that is exactly what I needed. How much longer do we have to wait? Do not worry, everything will turn out fine.",
        },
        {
            "id": "q-assistant-asks",
            "title": "Questions: the assistant asks",
            "text": "Shall I turn off the light in the living room? Do you want me to lock the front door? Shall I remind you of the meeting tomorrow morning? Is it too warm in the bedroom? Shall I lower the blinds in the whole house? Would you like the morning news? Shall I turn on the heating in the bathroom? Do you want milk on the shopping list? Should the alarm ring on Saturday too? Can you hear me well? Shall I read that message once more? Do you really want all the lights off?",
        },
        {
            "id": "q-asking-assistant",
            "title": "Questions: asking the assistant",
            "text": "How many degrees is it outside now? When does my first morning bus leave? Where did I leave my phone charger? Why is the light on the washing machine blinking? How much longer will the dishwasher run? Who rang the doorbell today? What is in my calendar tomorrow? How much electricity did we use this week? When were the plants last watered? What is the temperature in the children's room? Which window was left open? Where did I save that stew recipe?",
        },
        {
            "id": "q-choice",
            "title": "Questions: a choice of two",
            "text": "Would you like tea or coffee? Shall we go by train or by car? Should I send it today or tomorrow? Are we staying in or going out? Will you have soup or the main course straight away? Are you paying by card or in cash? Shall we meet at five or rather at six? Should I switch on the lamp or the ceiling light? Is this enough or shall I add more? Will you call him or will he call you? Shall we walk or wait for the tram? Do you want to hear it now or after dinner?",
        },
        {
            "id": "q-doctor",
            "title": "Questions: at the doctor's",
            "text": "Good morning, what brings you here? My throat has been sore for three days. Do you have a temperature as well? Around thirty eight in the evenings. Are you taking any medicine? Only cough drops. Are you allergic to anything? Not as far as I know. When did you last have a check-up? About two years ago. Can you take a deep breath? Does it hurt when you swallow? I will prescribe antibiotics, all right? Will you come back in a week?",
        },
        {
            "id": "q-directions",
            "title": "Questions: on the way",
            "text": "Excuse me, how do I get to the station? Go straight on and turn left at the pharmacy. Is it far from here? About ten minutes on foot. Is there a bus going there? Yes, number twelve, it stops just round the corner. Where can I buy a ticket? At the newsagent, or from the driver. Can I still catch the half past three train? If you hurry, certainly. Which platform does it leave from? I am afraid I cannot tell you. And do you know whether it is delayed? You had better ask at the ticket office.",
        },
        {
            "id": "q-why",
            "title": "Questions: a curious child",
            "text": "Why is the sky blue? Because the air scatters the sunlight. And why is it red in the evening? Because the light travels a longer way. Where does the sun go to sleep? Nowhere, it is the Earth that turns. Who switches off the stars? Nobody, the sun just outshines them by day. How high do birds fly? Some fly higher than planes. What do fish eat in winter? Almost nothing, they rest under the ice. Why do I have to go to bed when I am not tired? Because we get up early tomorrow. And may I read a little longer?",
        },
        {
            "id": "q-tags",
            "title": "Questions: checking and surprise",
            "text": "That is your bike, is it not? You locked the door, did you not? You really went there alone? He actually said that out loud? You are coming tomorrow, right? Is this supposed to be all? Have you two met already? She did not know about it at all? You did not forget the keys, did you? So we meet at seven? Are you serious about that? And nobody told you?",
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
    added = prompts.add_custom(voice, paragraph["text"], source=paragraph["title"])
    return {"added": added, "sentences": len(_sentences(paragraph["text"]))}
