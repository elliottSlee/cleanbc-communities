#!/usr/bin/env python3
"""Step 6 - commercial commute basins: a service-area geography for contractors.

BC's official boundaries are the wrong shape for "where will you travel to
work". Regional districts are too big - Peace River is larger than Austria -
and municipalities are too small, because most of the province's inhabited
places are unincorporated and belong to no municipality at all. A contractor
asked to tick municipalities cannot say "the Comox Valley"; asked to tick
regional districts, they accidentally commit to a fifth of the province.

This step builds a third geography on top of the join's output: roughly
45 *commute basins*, each a 45-60 minute driving corridor around one commercial
hub, grouped into macro regions. Every geoname in `out/geoname_population.csv`
lands in exactly one basin, so the unincorporated places the municipal list
drops - Errington, Roberts Creek, Merville, Royston - are covered by naming
their hub.

Three tables below are hand-authored, and they are the whole model:

  REGIONS   the macro regions, in the order the UI shows them.
  BASINS    one per hub. `hub` names a row of the source CSV; its coordinates
            come from that row, so no coordinate is typed here and a
            misspelled hub is a hard error rather than a dot in the ocean.
  ZONES     the barriers. A zone is a named set of places on the far side of
            water or a mountain pass, and it does two things: it overrides
            distance when assigning those places to a basin, and it marks them
            so the UI can leave them out until a contractor says they take
            ferries or drive passes.

Everything else is derived. A place with no zone joins the nearest hub among
the basins that draw from its census division, which keeps assignment inside
real geography: straight-line distance alone would put Salt Spring in Victoria
and Duncan next door to it.

    python3 06_basins.py [--source out/geoname_population.csv]
                         [--out out/geoname_basins.csv]
                         [--json out/service_areas.json]
                         [--report]

`--report` prints every basin with its members ordered by distance from the
hub, which is how the tables above get reviewed: a member far from its hub is
either a genuinely large basin or a mistake, and the two are easy to tell apart
by name.
"""

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE = os.path.join(HERE, "out", "geoname_population.csv")
DEFAULT_OUT = os.path.join(HERE, "out", "geoname_basins.csv")
DEFAULT_JSON = os.path.join(HERE, "out", "service_areas.json")

# How a place or a basin is reached, ordered by how much a contractor has to
# opt into: a road is the default, a ferry costs a sailing and a schedule, a
# pass costs winter tyres and an hour of mountain highway.
#
# REMOTE is a fourth level the brief did not ask for and BC needs anyway. A
# hundred-odd inhabited places here are neither ferry nor pass: they are two
# hundred kilometres of resource road, a winter road, or a float plane - Fort
# Ware, Tsay Keh Dene, the Sustut, Gwaii Haanas. Filing them under either of
# the other two would tell a contractor something false about the trip, so
# they get their own toggle.
ROAD, FERRY, PASS, REMOTE = "road", "ferry", "pass", "remote"

# Toggle order in the UI, and the order the JSON lists them in.
ACCESS_LEVELS = [ROAD, FERRY, PASS, REMOTE]

# Great-circle kilometres past which an unclassified place is called remote.
# A 60-minute drive on a BC highway is roughly 90 km of road, which is well
# under 120 km in a straight line, so nothing inside a real commute basin is
# caught by this and nothing caught by it is inside one.
DISTANT_KM = 120

# The 29 census divisions, by the name the province uses for the regional
# district that shares each one's boundary. Only used for reporting and for
# the `cds` field below to stay readable.
CD_NAMES = {
    "5901": "East Kootenay", "5903": "Central Kootenay",
    "5905": "Kootenay Boundary", "5907": "Okanagan-Similkameen",
    "5909": "Fraser Valley", "5915": "Metro Vancouver", "5917": "Capital",
    "5919": "Cowichan Valley", "5921": "Nanaimo", "5923": "Alberni-Clayoquot",
    "5924": "Strathcona", "5926": "Comox Valley", "5927": "qathet",
    "5929": "Sunshine Coast", "5931": "Squamish-Lillooet",
    "5933": "Thompson-Nicola", "5935": "Central Okanagan",
    "5937": "North Okanagan", "5939": "Columbia-Shuswap", "5941": "Cariboo",
    "5943": "Mount Waddington", "5945": "Central Coast", "5947": "North Coast",
    "5949": "Kitimat-Stikine", "5951": "Bulkley-Nechako",
    "5953": "Fraser-Fort George", "5955": "Peace River", "5957": "Stikine",
    "5959": "Northern Rockies",
}

REGIONS = [
    ("vi-south",          "Vancouver Island · South"),
    ("vi-central",        "Vancouver Island · Central"),
    ("vi-north",          "Vancouver Island · North"),
    ("sunshine-coast",    "Sunshine Coast & qathet"),
    ("lower-mainland",    "Lower Mainland"),
    ("fraser-valley",     "Fraser Valley & Canyon"),
    ("sea-to-sky",        "Sea to Sky"),
    ("thompson",          "Thompson–Nicola & Shuswap"),
    ("okanagan",          "Okanagan & Similkameen"),
    ("kootenay-west",     "West Kootenay & Boundary"),
    ("kootenay-east",     "East Kootenay & Columbia"),
    ("cariboo",           "Cariboo–Chilcotin & Central Coast"),
    ("northwest",         "Northwest Coast"),
    ("northern-interior", "Northern Interior"),
    ("prince-george",     "Prince George & Robson Valley"),
    ("peace-liard",       "Peace & Liard"),
]

# key, label, region, hub, access, cds, note
#
# `access` is how the *basin* is reached from the rest of its macro region, so
# it is the Malahat on Cowichan and a sailing on Salt Spring. `cds` is the set
# of census divisions a basin may claim places from; it defaults to the hub's
# own, and is widened only where one labour market straddles a divisional
# boundary. Notes name the places a contractor would expect to be told about,
# and are shown in the UI.
# `closed` keeps a basin out of the nearest-hub competition, so it holds only
# what its zone hands it. Every island basin needs it: Ganges is 24 km from
# Sidney across Haro Strait and would otherwise take the Saanich Peninsula off
# Victoria, which is the exact mistake the whole design exists to prevent.
B = lambda key, label, region, hub, access=ROAD, cds=(), note="", closed=False: dict(
    key=key, label=label, region=region, hub=hub, access=access,
    cds=tuple(cds), note=note, closed=closed)

BASINS = [
    # --- Vancouver Island · South -------------------------------------
    B("victoria", "Greater Victoria", "vi-south", "Victoria",
      note="Victoria, Saanich, Oak Bay, Esquimalt, View Royal, Sidney and the Saanich Peninsula."),
    B("west-shore", "West Shore & Sooke", "vi-south", "Sooke",
      note="Langford, Colwood, Metchosin, Highlands, and out Highway 14 to Port Renfrew."),
    B("gulf-islands-south", "Southern Gulf Islands", "vi-south", "Ganges",
      access=FERRY, cds=("5917", "5919"),
      note="Salt Spring, Pender, Mayne, Galiano, Saturna, Thetis. Every job is a sailing, and hopping between islands is often two.", closed=True),

    # --- Vancouver Island · Central -----------------------------------
    B("cowichan", "Cowichan Valley", "vi-central", "Duncan", access=PASS,
      note="Over the Malahat from Victoria: Duncan, North Cowichan, Chemainus, Ladysmith, Lake Cowichan."),
    B("nanaimo", "Nanaimo & Area", "vi-central", "Nanaimo",
      note="Nanaimo, Lantzville, Cedar, South Wellington. Gabriola is a sailing off the harbour."),
    B("oceanside", "Parksville–Qualicum", "vi-central", "Parksville",
      note="Parksville, Qualicum Beach, Errington, Coombs, Bowser, Deep Bay."),
    B("port-alberni", "Port Alberni Valley", "vi-central", "Port Alberni",
      access=PASS,
      note="Over the Alberni Summit on Highway 4: Port Alberni, Sproat Lake, Beaver Creek, Bamfield."),
    B("west-coast-vi", "Tofino–Ucluelet", "vi-central", "Tofino", access=PASS,
      note="Past Sutton Pass and another two hours: Tofino, Ucluelet, Hitacu, Esowista, Macoah."),

    # --- Vancouver Island · North -------------------------------------
    B("comox-valley", "Comox Valley", "vi-north", "Courtenay",
      note="Courtenay, Comox, Cumberland, Royston, Merville, Black Creek, Union Bay."),
    B("campbell-river", "Campbell River & Area", "vi-north", "Campbell River",
      note="Campbell River, Campbellton, Quinsam, Sayward, Woss. Quadra and Cortes are sailings."),
    B("gold-river", "Gold River, Tahsis & Zeballos", "vi-north", "Gold River",
      access=PASS,
      note="Over the island spine on Highway 28, then gravel to Tahsis and Zeballos."),
    B("north-island", "North Island", "vi-north", "Port McNeill",
      note="Port Hardy, Port McNeill, Port Alice, Coal Harbour, Holberg, Winter Harbour. Alert Bay, Sointula and the Broughton inlets are boat trips."),

    # --- Sunshine Coast & qathet --------------------------------------
    B("sechelt", "Lower Sunshine Coast", "sunshine-coast", "Sechelt",
      access=FERRY,
      note="Gibsons, Roberts Creek, Sechelt, Davis Bay, Halfmoon Bay. Forty minutes from Horseshoe Bay, and no road around."),
    B("pender-harbour", "Pender Harbour & Egmont", "sunshine-coast", "Madeira Park",
      access=FERRY,
      note="Madeira Park, Garden Bay, Egmont, Earls Cove — an hour beyond Sechelt."),
    B("powell-river", "qathet / Powell River", "sunshine-coast", "Powell River",
      access=FERRY,
      note="Powell River, Westview, Lund, Saltery Bay. Two ferries from Vancouver; Texada is a third."),

    # --- Lower Mainland -----------------------------------------------
    B("vancouver", "Vancouver & Burnaby", "lower-mainland", "Vancouver",
      note="Vancouver, Burnaby, New Westminster, Musqueam."),
    B("north-shore", "North Shore", "lower-mainland", "North Vancouver",
      note="City and District of North Vancouver, West Vancouver, Lions Bay. Bowen Island is a sailing from Horseshoe Bay."),
    B("richmond-delta", "Richmond & Delta", "lower-mainland", "Richmond",
      note="Richmond, Delta, Ladner, Tsawwassen, Steveston."),
    B("surrey-langley", "Surrey, White Rock & Langley", "lower-mainland", "Surrey",
      note="Surrey, White Rock, City and Township of Langley, Cloverdale, Semiahmoo."),
    B("tri-cities", "Tri-Cities & Ridge Meadows", "lower-mainland", "Coquitlam",
      note="Coquitlam, Port Coquitlam, Port Moody, Anmore, Belcarra, Maple Ridge, Pitt Meadows."),

    # --- Fraser Valley & Canyon ---------------------------------------
    B("abbotsford-mission", "Abbotsford & Mission", "fraser-valley", "Abbotsford",
      note="Abbotsford, Mission, Matsqui, Sumas Prairie, Deroche."),
    B("chilliwack", "Chilliwack & Agassiz", "fraser-valley", "Chilliwack",
      note="Chilliwack, Sardis, Agassiz, Harrison Hot Springs, Cultus Lake, Rosedale."),
    B("hope-canyon", "Hope & the Fraser Canyon", "fraser-valley", "Hope",
      note="Hope, Yale, Spuzzum, Boston Bar, North Bend."),

    # --- Sea to Sky ----------------------------------------------------
    B("squamish", "Squamish & Howe Sound", "sea-to-sky", "Squamish",
      note="Squamish, Brackendale, Britannia Beach, Furry Creek, Garibaldi Highlands."),
    B("whistler-pemberton", "Whistler & Pemberton", "sea-to-sky", "Whistler",
      note="Whistler, Pemberton, Mount Currie, Birken, D'Arcy."),
    B("lillooet", "Lillooet & Bridge River", "sea-to-sky", "Lillooet", access=PASS,
      note="Over the Duffey Lake road from Pemberton, or up from Cache Creek. The Duffey closes in winter."),

    # --- Thompson–Nicola & Shuswap -------------------------------------
    B("kamloops", "Kamloops & Area", "thompson", "Kamloops",
      note="Kamloops, Chase, Savona, Pritchard, Logan Lake, Sun Peaks, Tk'emlúps."),
    B("merritt", "Merritt & the Nicola Valley", "thompson", "Merritt", access=PASS,
      note="Over the Coquihalla from either end: Merritt, Lower Nicola, Douglas Lake, Shulus."),
    B("cache-creek", "Cache Creek, Ashcroft & Clinton", "thompson", "Cache Creek",
      note="The Highway 97 junction: Cache Creek, Ashcroft, Clinton, Spences Bridge, 70 Mile House."),
    B("north-thompson", "North Thompson", "thompson", "Clearwater",
      note="Barriere, Clearwater, Vavenby, Blue River, Avola."),
    B("lytton", "Lytton & the Thompson Canyon", "thompson", "Lytton",
      note="Lytton, the Lytton First Nation reserves, Botanie, Stein, Kanaka Bar."),
    B("shuswap", "Shuswap", "thompson", "Salmon Arm", cds=("5939",),
      note="Salmon Arm, Sicamous, Sorrento, Blind Bay, Tappen, Malakwa."),

    # --- Okanagan & Similkameen ----------------------------------------
    B("kelowna", "Central Okanagan", "okanagan", "Kelowna",
      note="Kelowna, West Kelowna, Lake Country, Peachland, Westbank, Winfield."),
    B("vernon", "North Okanagan", "okanagan", "Vernon",
      note="Vernon, Coldstream, Armstrong, Spallumcheen, Enderby, Lumby, Falkland."),
    B("penticton", "South Okanagan", "okanagan", "Penticton",
      note="Penticton, Summerland, Naramata, Okanagan Falls, Kaleden."),
    B("oliver-osoyoos", "Oliver, Osoyoos & Keremeos", "okanagan", "Oliver",
      note="Oliver, Osoyoos, Keremeos, Cawston, the south valley."),
    B("similkameen", "Similkameen", "okanagan", "Princeton", access=PASS,
      note="Over Allison Pass from Hope: Princeton, Tulameen, Coalmont, Hedley."),

    # --- West Kootenay & Boundary ---------------------------------------
    B("nelson", "Nelson & the Slocan", "kootenay-west", "Nelson",
      note="Nelson, Salmo, Slocan, Silverton, New Denver, Kaslo, Balfour, Ymir."),
    B("trail-castlegar", "Trail, Castlegar & Rossland", "kootenay-west", "Trail",
      cds=("5903", "5905"),
      note="One labour market across two regional districts: Trail, Castlegar, Rossland, Fruitvale, Warfield, Montrose."),
    B("creston", "Creston Valley", "kootenay-west", "Creston", access=PASS,
      note="Over the Kootenay Pass from Salmo, or across on the Kootenay Lake ferry."),
    B("arrow-lakes", "Arrow Lakes", "kootenay-west", "Nakusp", access=FERRY,
      note="The Needles and Galena Bay cable ferries reach it from every direction."),
    B("boundary", "Boundary", "kootenay-west", "Grand Forks", access=PASS,
      note="Over the Paulson and Eholt summits: Grand Forks, Greenwood, Midway, Christina Lake, Beaverdell."),

    # --- East Kootenay & Columbia ---------------------------------------
    B("cranbrook", "Cranbrook & Kimberley", "kootenay-east", "Cranbrook",
      note="Cranbrook, Kimberley, Marysville, Wardner, Moyie, ʔaq'am."),
    B("elk-valley", "Elk Valley", "kootenay-east", "Fernie",
      note="Fernie, Sparwood, Elkford, Hosmer, Jaffray."),
    B("columbia-valley", "Columbia Valley", "kootenay-east", "Invermere",
      note="Invermere, Radium Hot Springs, Canal Flats, Fairmont Hot Springs, Windermere."),
    B("golden", "Golden & Kicking Horse", "kootenay-east", "Golden",
      access=PASS, cds=("5939",),
      note="Rogers Pass one way, Kicking Horse the other, and both close for avalanche control."),
    B("revelstoke", "Revelstoke", "kootenay-east", "Revelstoke", access=PASS,
      cds=("5939",),
      note="Between Eagle Pass and Rogers Pass, with nothing for an hour in either direction."),

    # --- Cariboo–Chilcotin & Central Coast -------------------------------
    B("williams-lake", "Williams Lake & Area", "cariboo", "Williams Lake",
      note="Williams Lake, Sugarcane, 150 Mile House, Horsefly, Likely, Soda Creek, McLeese Lake."),
    B("quesnel", "Quesnel & Area", "cariboo", "Quesnel",
      note="Quesnel, Bouchie Lake, Nazko, Wells, Barkerville, Hixon's south end."),
    B("south-cariboo", "South Cariboo", "cariboo", "100 Mile House",
      note="100 Mile House, Lac la Hache, Bridge Lake, Canim Lake, Forest Grove."),
    B("chilcotin", "Chilcotin", "cariboo", "Alexis Creek",
      note="Highway 20 west of the Fraser: Alexis Creek, Redstone, Tatla Lake, Nemiah, Chilanko Forks."),
    B("west-chilcotin", "West Chilcotin", "cariboo", "Anahim Lake",
      note="Anahim Lake, Ulkatcho, Nimpo Lake, Towdystan, Kleena Kleene — another two hours past Alexis Creek."),
    B("bella-coola", "Bella Coola Valley", "cariboo", "Hagensborg", access=PASS,
      note="Down the Heckman Pass switchbacks from the Chilcotin, or in on the ferry."),
    B("central-coast-marine", "Central Coast (Bella Bella & Klemtu)", "cariboo",
      "Bella Bella 1", access=FERRY, cds=("5945", "5949"),
      note="Bella Bella, Klemtu, Ocean Falls, Shearwater, Namu. Ferry or float plane, and a separate trip to each.", closed=True),

    # --- Northwest Coast --------------------------------------------------
    B("prince-rupert", "Prince Rupert & the North Coast", "northwest", "Prince Rupert",
      note="Prince Rupert, Port Edward, Lax Kw'alaams, Metlakatla, Kitkatla."),
    B("haida-gwaii", "Haida Gwaii", "northwest", "Masset", access=FERRY, cds=("5947",),
      note="Old Massett, Port Clements, Tlell, Skidegate, Daajing Giids, Sandspit. Seven hours on the Skeena, or a flight.", closed=True),
    B("terrace-kitimat", "Terrace & Kitimat", "northwest", "Terrace",
      note="Terrace, Kitimat, Thornhill, Kitamaat Village, Kitselas, Kitsumkalum."),
    B("hazeltons", "The Hazeltons", "northwest", "New Hazelton",
      note="New Hazelton, Hazelton, South Hazelton, Kispiox, Gitanmaax, Gitsegukla, Gitwangak."),
    B("nass-valley", "Nass Valley", "northwest", "New Aiyansh",
      note="Gitlaxt'aamiks, Gitwinksihlkw, Laxgalts'ap, Gingolx, Nass Camp."),
    B("stewart", "Stewart & the Bear Valley", "northwest", "Stewart", access=PASS,
      note="Highway 37A over Bear Pass: 65 km from the junction with nothing in between."),

    # --- Northern Interior -------------------------------------------------
    B("smithers", "Bulkley Valley", "northern-interior", "Smithers",
      note="Smithers, Telkwa, Houston, Witset, Quick, Topley."),
    B("burns-lake", "Lakes District", "northern-interior", "Burns Lake",
      note="Burns Lake, Southside, Francois Lake, Granisle, Decker Lake."),
    B("nechako", "Nechako", "northern-interior", "Vanderhoof",
      note="Vanderhoof, Fort Fraser, Fraser Lake, Endako, Stoney Creek."),
    B("fort-st-james", "Fort St. James & Stuart Lake", "northern-interior",
      "Fort St. James", cds=("5951", "5957"),
      note="Fort St. James, Nak'azdli, Tachie, Middle River, and the Takla and Sustut country beyond the road."),
    B("dease-lake", "Dease Lake & the Stikine", "northern-interior", "Dease Lake",
      cds=("5949", "5957"),
      note="Highway 37 north: Dease Lake, Iskut, Telegraph Creek, Good Hope Lake, Jade City."),
    B("atlin", "Atlin & the Far Northwest", "northern-interior", "Atlin",
      cds=("5957",),
      note="Reached through the Yukon: ninety minutes from Whitehorse, two days from Vancouver."),

    # --- Prince George & Robson Valley --------------------------------------
    B("prince-george", "Prince George & Area", "prince-george", "Prince George",
      note="Prince George, Beaverley, Pineview, Shelley, Hixon, Bear Lake."),
    B("mackenzie", "Mackenzie", "prince-george", "Mackenzie",
      note="Mackenzie, McLeod Lake, Parsnip, and the south end of Williston Reservoir."),
    B("williston", "Williston & the Rocky Mountain Trench", "prince-george",
      "Tsay Keh Dene", access=REMOTE, cds=("5955",),
      note="Tsay Keh Dene, Kwadacha/Fort Ware, Ingenika. Two hundred kilometres of resource road north of Mackenzie, or a flight.", closed=True),
    B("robson-valley", "Robson Valley", "prince-george", "Valemount", access=PASS,
      note="Valemount, McBride, Dunster, Tête Jaune Cache, over the Yellowhead."),

    # --- Peace & Liard --------------------------------------------------------
    B("dawson-creek", "Dawson Creek & the South Peace", "peace-liard", "Dawson Creek",
      note="Dawson Creek, Pouce Coupe, Rolla, Tomslake, Arras, Farmington."),
    B("fort-st-john", "Fort St. John & the North Peace", "peace-liard", "Fort St. John",
      note="Fort St. John, Taylor, Hudson's Hope, Charlie Lake, Baldonnel, Cecil Lake."),
    B("chetwynd", "Chetwynd & Tumbler Ridge", "peace-liard", "Chetwynd", access=PASS,
      note="Over the Pine Pass from Prince George: Chetwynd, Tumbler Ridge, Moberly Lake, Jackfish."),
    B("pink-mountain", "Alaska Highway North", "peace-liard", "Pink Mountain",
      note="Wonowon, Pink Mountain, Sikanni Chief, Buckinghorse River, Trutch and the Beatton ranches."),
    B("fort-nelson", "Fort Nelson", "peace-liard", "Fort Nelson", cds=("5959",),
      note="Fort Nelson, Prophet River, Fontas, Kahntah, and the Northern Rockies municipality."),
    B("liard", "Liard & the Northern Rockies Highway", "peace-liard", "Muncho Lake",
      cds=("5959", "5957"),
      note="Summit Lake, Toad River, Muncho Lake, Liard River, Coal River, Fireside, Lower Post. Four hundred kilometres of Alaska Highway to Watson Lake."),
]

# Barrier zones: the places on the far side of water, a pass, or the end of the
# road. A zone does two jobs - it overrides distance when assigning its places
# to a basin, and it stamps them with the access a contractor has to opt into.
#
# `access` is how the zone's places are reached *from their basin's hub*. So
# Hornby and Denman hang off Courtenay and are FERRY, while Haida Gwaii *is*
# its basin and is ROAD, with the sailing carried by the basin itself.
#
# Membership is by exact `bc_geographic_name`, or by bounding boxes where one
# separates cleanly. Boxes leak - Buckley Bay and Fanny Bay sit on the same
# water as Denman but on the Island side - so a box is used only where every
# place inside it was listed and checked, and `cds` narrows it further.
Z = lambda key, label, basin, access, names=(), boxes=(), cds=(): dict(
    key=key, label=label, basin=basin, access=access,
    names=frozenset(names), boxes=tuple(boxes), cds=tuple(cds))

ZONES = [
    # --- ferry-dependent sub-locales hanging off a mainland or Island hub
    Z("hornby-denman", "Hornby & Denman Islands", "comox-valley", FERRY,
      names=["Hornby Island", "Denman Island"]),
    Z("gabriola", "Gabriola Island", "nanaimo", FERRY,
      names=["Gabriola", "Gabriola Island 5", "Ma-Guala 6"]),
    Z("bowen-island", "Bowen Island", "north-shore", FERRY,
      names=["Bowen Island", "Bowen Bay", "Cowans Point", "Mount Gardner",
             "Snug Cove", "Tunstall Bay"]),
    Z("texada-island", "Texada Island", "powell-river", FERRY,
      names=["Van Anda", "Gillies Bay", "Blubber Bay"]),
    Z("discovery-islands", "Quadra, Cortes & Read Islands", "campbell-river",
      FERRY,
      names=["Quathiaski Cove", "Heriot Bay", "Granite Bay", "Bold Point",
             "Cape Mudge 10", "Drew Harbour 9", "Open Bay 8", "Village Bay 7",
             "Yaculta", "Surge Narrows", "Tatpo-oose 10", "Read Island",
             "Whaletown", "Mansons Landing", "Cortes Bay", "Squirrel Cove",
             "Squirrel Cove 8", "Seaford", "Tork 7", "Quequa 6"]),
    Z("malcolm-cormorant", "Alert Bay & Sointula", "north-island", FERRY,
      names=["Alert Bay", "Alert Bay 1", "Alert Bay 1A", "Sointula",
             "Malcolm Island 8", "Mitchell Bay", "Nimpkish 2"]),
    Z("broughton-inlets", "Broughton Archipelago & the mainland inlets",
      "north-island", FERRY,
      names=["Kingcome", "Kingcome Inlet", "Hopetown", "Sullivan Bay",
             "Shawl Bay", "Scott Cove", "Echo Bay", "Health Bay",
             "Thompson Sound", "Meem Quam Leese", "Minstrel Island",
             "Cracroft", "Warner Bay", "Simoom Sound", "Gilford Island"]),
    Z("sandspit", "Sandspit & Moresby Island", "haida-gwaii", FERRY,
      names=["Sandspit", "Alliford Bay", "Copper Bay"]),

    # --- whole basins that happen to be islands: the sailing is the basin's,
    #     so members are ROAD once you are there.
    Z("gulf-islands", "Southern Gulf Islands", "gulf-islands-south", ROAD,
      names=["Ganges", "Fernwood", "Fulford Harbour", "Fulford Harbour 5",
             "Beaver Point", "Vesuvius", "Central Settlement", "Burgoyne Bay",
             "Galiano Island 9", "North Galiano", "Sturdies Bay", "Montague",
             "Mayne Island", "Mayne Island 6", "Miners Bay", "Village Bay",
             "Pender Island", "Pender Island 8", "Port Washington",
             "Hope Bay", "Saturna", "Saturna Island 7", "Lighthouse Point",
             "Thetis Island", "Kuper Island", "Penelakut Island",
             "Piers Island", "Prevost Island"]),
    Z("central-coast-water", "Bella Bella, Klemtu & the outer coast",
      "central-coast-marine", FERRY,
      names=["Old Bella Bella", "Campbell Island", "Shearwater",
             "Ocean Falls", "Namu", "Klemtu", "Dawsons Landing", "Oweekeno",
             "Kimsquit", "Tallheo", "South Bentinck", "Katit 1",
             "China Hat 6", "Kitasu 3"]),

    # --- the end of the road: resource roads, winter roads and float planes.
    #     Ordered before the Haida Gwaii box so the outer coast wins.
    Z("gwaii-haanas", "Gwaii Haanas & the west coast", "haida-gwaii", REMOTE,
      boxes=[(52.0, 53.05, -133.6, -131.0), (53.05, 54.4, -133.6, -132.6)],
      cds=("5947",)),
    Z("haida-gwaii-road", "Graham Island", "haida-gwaii", ROAD,
      boxes=[(52.0, 54.4, -133.6, -131.0)], cds=("5947",)),
    # --- the coast north of Bella Bella. Two regional districts of fjord and
    #     island where the only roads are Highway 16 into Prince Rupert and
    #     Highway 37 into Kitimat; everything else is a boat. Left to distance
    #     alone, ninety Tsimshian, Gitga'at, Haisla and Kitasoo communities
    #     read as a 150 km drive up a channel that has no road beside it.
    #
    #     The road corridor is matched first and everything else in the
    #     division falls through to water. The corridor box is Highway 16 from
    #     the Skeena crossings to Prince Rupert and the Port Edward spur; it is
    #     drawn to leave Metlakatla, Dodge Cove, Osland and Port Essington on
    #     the water side, because that is what they are.
    Z("prince-rupert-road", "Highway 16 & the Port Edward spur", "prince-rupert",
      ROAD, boxes=[(54.16, 54.42, -130.36, -129.30)], cds=("5947",)),
    Z("north-coast-water", "Tsimshian & Gitga'at waters", "prince-rupert", FERRY,
      boxes=[(52.00, 55.20, -131.00, -128.50)], cds=("5947",)),
    Z("douglas-channel", "Douglas Channel & Gardner Canal", "terrace-kitimat",
      FERRY, boxes=[(53.00, 53.78, -129.60, -127.60)], cds=("5949",)),
    Z("kitasoo-waters", "Kitasoo & Heiltsuk waters", "central-coast-marine",
      FERRY, boxes=[(52.00, 53.00, -129.60, -127.60)], cds=("5949",)),

    # --- the Central Coast. `bella-coola` is the valley road in from the
    #     Chilcotin and nothing else; the rest of the division is Heiltsuk,
    #     Wuikinuxv and Nuxalk country on islands and inlets with no road at
    #     all. The road box is Highway 20 from Atnarko down to the wharf, cut
    #     at -126.80 so Tallheo stays on the far side of North Bentinck Arm,
    #     which is where it is.
    Z("bella-coola-road", "The Bella Coola valley road", "bella-coola", ROAD,
      boxes=[(52.30, 52.50, -126.80, -125.70)], cds=("5945",)),
    Z("central-coast-inlets", "Heiltsuk, Wuikinuxv & Nuxalk waters",
      "central-coast-marine", FERRY,
      boxes=[(51.00, 53.00, -129.60, -125.70)], cds=("5945",)),

    # --- the Omineca and the upper Skeena. Gravel, trail and float plane:
    #     Germansen Landing and Manson Creek are the old Omineca gold road out
    #     of Fort St. James, Takla Landing is the lake, and Kisgegas and Kuldo
    #     are up the Skeena beyond the end of the Kispiox road.
    Z("upper-skeena", "Kisgegas & Kuldo", "hazeltons", REMOTE,
      boxes=[(55.10, 57.00, -129.00, -127.00)], cds=("5951",)),
    Z("omineca-takla", "Omineca, Takla & the Driftwood", "fort-st-james", REMOTE,
      boxes=[(55.10, 57.00, -127.00, -124.00)], cds=("5951",)),
    Z("ootsa-south", "South of Ootsa Lake", "burns-lake", REMOTE,
      boxes=[(52.80, 53.55, -127.50, -124.50)], cds=("5951",)),

    Z("williston-trench", "Williston & the Rocky Mountain Trench", "williston",
      ROAD, boxes=[(55.0, 60.0, -128.0, -124.0)], cds=("5955",)),
    Z("takla-sustut", "Takla & the Sustut", "fort-st-james", REMOTE,
      names=["Bear Lake", "Bear Lake (Fort Connelly) 4",
             "Bear Lake (Tsaytut Bay) 1B", "Tsaytut Island 1C",
             "Tsupmeet (Patcha Creek) 5", "Klewaduska (Cataract) 6",
             "Bear River (Sustut River) 3", "Connolly", "Driftwood"],
      cds=("5957",)),
    Z("stikine-backcountry", "The Stikine backcountry", "dease-lake", REMOTE,
      names=["Fourth Cabin", "Fifth Cabin", "Hyland Post", "Sheslay",
             "Callison Ranch", "Tulsequah", "Saloon", "Hyland Ranch"],
      cds=("5957",)),
    Z("atlin-chilkoot", "Chilkoot & Taku", "atlin", REMOTE,
      names=["Bennett", "Lindeman", "Engineer", "Taku", "Scotia Bay",
             "Rupert", "Surprise", "Rainy Hollow", "Pleasant Camp"],
      cds=("5957",)),
]

# Places whose basin no rule gets right. Each is a judgement about a labour
# market rather than a correction to the data, so each carries its reason.
#
# Lions Bay was considered and left on the North Shore: it is on the Sea to
# Sky highway but twenty minutes from West Vancouver and forty from Squamish.
OVERRIDES = {
    "Castlegar": ("trail-castlegar", "one labour market with Trail"),
    "Ootischenia": ("trail-castlegar", "Castlegar's south bank"),
    "Genelle": ("trail-castlegar", "on the highway between Trail and Castlegar"),
    "Keremeos": ("oliver-osoyoos", "trades down the valley, not over Allison Pass"),
    "Cawston": ("oliver-osoyoos", "trades down the valley, not over Allison Pass"),
    "Hedley": ("similkameen", "on Highway 3 between Princeton and Keremeos"),
}


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance. Not a driving distance, and not used as one:
    it only ranks candidate hubs that the census division has already
    narrowed to a plausible set."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# Geoname types that name an incorporated municipality, preferred when a hub
# name is carried by more than one row (Abbotsford is both a City and a
# Community at the same coordinates).
MUNICIPAL_TYPES = ("City", "District Municipality", "Town", "Village",
                   "Resort Municipality")


def load_places(path):
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        try:
            lat, lon = float(r["lat"]), float(r["lon"])
        except (TypeError, ValueError):
            continue
        cd = (r.get("csd_uid") or "")[:4]
        if not cd:
            continue
        pop = r.get("place_population") or ""
        out.append({
            "id": int(r["geoname_id"]),
            "name": r["bc_geographic_name"],
            "type": r["geoname_type"],
            "lat": lat, "lon": lon, "cd": cd,
            "pop": int(pop) if pop.isdigit() else None,
        })
    return out


def resolve_hubs(places):
    """Turn each basin's `hub` name into the row that is that place.

    A name can repeat - `North Vancouver` is a City and a District, and
    several municipalities appear a second time as a Community at the same
    point. The municipal row wins, then the larger population, and the choice
    is deterministic either way. A hub that matches nothing is a typo in the
    table above and stops the run.
    """
    index = {}
    for p in places:
        index.setdefault(p["name"], []).append(p)
    hubs, missing = {}, []
    for b in BASINS:
        cands = index.get(b["hub"], [])
        if not cands:
            missing.append((b["key"], b["hub"]))
            continue
        muni = [c for c in cands if c["type"] in MUNICIPAL_TYPES]
        pool = muni or cands
        pool.sort(key=lambda c: (-(c["pop"] or 0), c["id"]))
        hubs[b["key"]] = pool[0]
    if missing:
        lines = "\n".join(f"  {k}: no place named {h!r}" for k, h in missing)
        raise SystemExit(f"unknown hub name(s):\n{lines}")
    return hubs


def basin_cds(b, hubs):
    """The census divisions a basin may claim from: its own declaration, or
    its hub's division when it declares none."""
    return set(b["cds"]) or {hubs[b["key"]]["cd"]}


def zone_of(place, zones):
    """The first zone that claims this place, so order is meaning: a specific
    zone listed before a general one wins, which is how Gwaii Haanas takes the
    outer coast before the Graham Island box takes the rest of Haida Gwaii."""
    for z in zones:
        if z["cds"] and place["cd"] not in z["cds"]:
            continue
        if place["name"] in z["names"]:
            return z
        for la0, la1, lo0, lo1 in z["boxes"]:
            if la0 <= place["lat"] <= la1 and lo0 <= place["lon"] <= lo1:
                return z
    return None


def assign(places, hubs):
    by_key = {b["key"]: b for b in BASINS}
    for z in ZONES:
        if z["basin"] not in by_key:
            raise SystemExit(f"zone {z['key']!r} names unknown basin {z['basin']!r}")
    for name, (key, _) in OVERRIDES.items():
        if key not in by_key:
            raise SystemExit(f"override {name!r} names unknown basin {key!r}")

    # Which basins each census division can offer.
    from_cd = {}
    for b in BASINS:
        if b["closed"]:
            continue
        for cd in basin_cds(b, hubs):
            from_cd.setdefault(cd, []).append(b["key"])

    fed_by_zone = {z["basin"] for z in ZONES} | {k for k, _ in OVERRIDES.values()}
    starved = [b["key"] for b in BASINS if b["closed"] and b["key"] not in fed_by_zone]
    if starved:
        raise SystemExit("closed basin with no zone to fill it: " + ", ".join(starved))

    orphan_cds = sorted(set(p["cd"] for p in places) - set(from_cd))
    if orphan_cds:
        names = ", ".join(f"{c} {CD_NAMES.get(c, '?')}" for c in orphan_cds)
        raise SystemExit(f"no basin draws from: {names}")

    assigned = []
    for p in places:
        hub_of = next((k for k, h in hubs.items() if h["id"] == p["id"]), None)
        zone = zone_of(p, ZONES)
        override = OVERRIDES.get(p["name"])

        if hub_of:
            key, how, access = hub_of, "hub", ROAD
        elif override:
            key, how, access = override[0], "override", ROAD
        elif zone:
            key, how, access = zone["basin"], f"zone:{zone['key']}", zone["access"]
        else:
            cands = from_cd[p["cd"]]
            key = min(cands, key=lambda k: (
                haversine_km(p["lat"], p["lon"], hubs[k]["lat"], hubs[k]["lon"]), k))
            how, access = "nearest", ROAD

        h = hubs[key]
        km = haversine_km(p["lat"], p["lon"], h["lat"], h["lon"])

        # The backstop. There is no road network in this repository, so a
        # place the tables did not classify is assumed to be an ordinary
        # drive - and that assumption fails in exactly one direction, on the
        # thirty-odd trapline localities and lake reserves nothing names.
        # Beyond DISTANT_KM it cannot be a 45-60 minute corridor whatever the
        # roads do, so it is marked remote rather than quietly offered as a
        # drive. The tag is visible in `assigned_by`, and a place that turns
        # out to be ordinary belongs in a zone above, not in a smaller number
        # here.
        if how == "nearest" and access == ROAD and km > DISTANT_KM:
            access, how = REMOTE, "nearest+beyond-range"

        assigned.append({
            **p,
            "basin": key,
            "hub": h["name"],
            "is_hub": bool(hub_of),
            "access": access,
            "assigned_by": how,
            "km": round(km, 1),
        })
    return assigned


FIELDS = ["geoname_id", "bc_geographic_name", "geoname_type", "lat", "lon",
          "place_population", "cd_uid", "cd_name", "macro_region",
          "macro_region_label", "basin", "basin_label", "basin_hub",
          "is_hub", "basin_access", "place_access", "assigned_by",
          "hub_distance_km"]


def write_csv(path, rows, region_label, by_key):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for r in sorted(rows, key=lambda r: (r["basin"], -(r["pop"] or 0), r["name"])):
            b = by_key[r["basin"]]
            w.writerow([
                r["id"], r["name"], r["type"], f"{r['lat']:.7f}", f"{r['lon']:.7f}",
                "" if r["pop"] is None else r["pop"],
                r["cd"], CD_NAMES.get(r["cd"], ""),
                b["region"], region_label[b["region"]],
                b["key"], b["label"], r["hub"],
                "TRUE" if r["is_hub"] else "FALSE",
                b["access"], r["access"], r["assigned_by"], f"{r['km']:.1f}",
            ])


def write_json(path, rows, hubs, by_key):
    """One self-contained file for the web page: the tables, then every place
    as a fixed-order array. Objects per place would triple the size for no
    gain, so the key order travels once in `fields`."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    order = {b["key"]: i for i, b in enumerate(BASINS)}
    counts = {}
    pops = {}
    for r in rows:
        counts[r["basin"]] = counts.get(r["basin"], 0) + 1
        pops[r["basin"]] = pops.get(r["basin"], 0) + (r["pop"] or 0)

    doc = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "pipeline/out/geoname_population.csv",
        "regions": [
            {"key": k, "label": lab,
             "basins": [b["key"] for b in BASINS if b["region"] == k]}
            for k, lab in REGIONS
        ],
        "basins": [
            {"key": b["key"], "label": b["label"], "region": b["region"],
             "hub": hubs[b["key"]]["name"], "hubId": hubs[b["key"]]["id"],
             "lat": round(hubs[b["key"]]["lat"], 5),
             "lon": round(hubs[b["key"]]["lon"], 5),
             "access": b["access"], "note": b["note"],
             "places": counts.get(b["key"], 0),
             "population": pops.get(b["key"], 0)}
            for b in BASINS
        ],
        "fields": ["id", "name", "type", "lat", "lon", "pop", "basin",
                   "access", "isHub"],
        "places": [
            [r["id"], r["name"], r["type"], round(r["lat"], 5), round(r["lon"], 5),
             r["pop"], r["basin"], r["access"], 1 if r["is_hub"] else 0]
            for r in sorted(rows, key=lambda r: (order[r["basin"]],
                                                 -(r["pop"] or 0), r["name"]))
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))


def report(rows, hubs, by_key, region_label):
    groups = {}
    for r in rows:
        groups.setdefault(r["basin"], []).append(r)
    for b in BASINS:
        g = sorted(groups.get(b["key"], []), key=lambda r: -r["km"])
        pop = sum(r["pop"] or 0 for r in g)
        print(f"\n=== {b['label']}  [{b['key']}]  {region_label[b['region']]}"
              f"  hub {hubs[b['key']]['name']}  access {b['access']}")
        print(f"    {len(g)} places, {pop:,} people, "
              f"farthest {g[0]['km'] if g else 0:.0f} km")
        for r in g:
            tag = "HUB" if r["is_hub"] else r["access"][:4]
            print(f"      {r['km']:7.1f} km  {tag:4}  {r['name'][:38]:38}"
                  f" {r['type'][:20]:20} {r['assigned_by']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--json", default=DEFAULT_JSON)
    ap.add_argument("--report", action="store_true",
                    help="print every basin's members, farthest first")
    args = ap.parse_args(argv)

    if not os.path.exists(args.source):
        raise SystemExit(f"{args.source} not found - run `make join` first")

    places = load_places(args.source)
    hubs = resolve_hubs(places)
    rows = assign(places, hubs)
    by_key = {b["key"]: b for b in BASINS}
    region_label = dict(REGIONS)

    write_csv(args.out, rows, region_label, by_key)
    write_json(args.json, rows, hubs, by_key)

    if args.report:
        report(rows, hubs, by_key, region_label)

    far = sorted(rows, key=lambda r: -r["km"])[:12]
    print(f"\n{len(REGIONS)} macro regions, {len(BASINS)} commute basins, "
          f"{len(rows)} places")
    print(f"wrote {os.path.relpath(args.out, HERE)} and "
          f"{os.path.relpath(args.json, HERE)}")
    by_how = {}
    for r in rows:
        k = r["assigned_by"].split(":")[0]
        by_how[k] = by_how.get(k, 0) + 1
    print("assigned by: " + ", ".join(f"{k} {v}" for k, v in sorted(by_how.items())))
    print("farthest from a hub:")
    for r in far:
        print(f"  {r['km']:7.1f} km  {r['name'][:34]:34} -> {r['basin']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
