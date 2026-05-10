from ember_memory.ingest import chunk_markdown

text = """Star Wars Lore Archive
Galactic Historical Record: The Fall of Mandalore
Overview
Mandalore was once one of the most feared military powers in the galaxy. Known for its warrior culture, advanced beskar armor, and clan-based political structure, the planet became central to multiple galactic conflicts over thousands of years. During the late Republic era, Mandalore underwent dramatic ideological shifts that fractured its people and weakened its defenses.
Rise of the New Mandalorians
Following generations of devastating civil war, Duchess Satine Kryze led a pacifist political movement known as the New Mandalorians. Her administration attempted to distance Mandalore from its violent past by banning traditional weapons, discouraging military expansion, and rebuilding major cities such as Sundari beneath protective domes.
Many traditionalist clans rejected Satine's reforms. These groups believed Mandalorian identity was inseparable from combat training, armor craftsmanship, and martial honor. Tensions between the pacifists and the traditionalists escalated over time.
Death Watch Insurgency
A militant faction called Death Watch emerged under the leadership of Pre Vizsla. Publicly, the group claimed to preserve authentic Mandalorian culture. Secretly, Death Watch sought to overthrow Satine's government and restore warrior rule.
Death Watch formed temporary alliances with criminal syndicates and outside powers to destabilize Mandalore. During the Clone Wars, the faction cooperated with the Shadow Collective, a criminal alliance organized by the former Sith Lord Maul.
Maul's Seizure of Power
Maul manipulated political unrest on Mandalore to seize control of the planet. After engineering a crisis involving organized crime, he defeated Pre Vizsla in ritual combat and claimed leadership according to ancient Mandalorian tradition.
Not all members of Death Watch accepted Maul as ruler. A faction led by Bo-Katan Kryze refused to follow an outsider. This division triggered additional internal conflict and further destabilized Mandalore.
The Siege of Mandalore
Near the end of the Clone Wars, Republic forces led by Ahsoka Tano and Commander Rex launched the Siege of Mandalore to remove Maul from power. The operation succeeded, but events rapidly changed when Order 66 was issued across the galaxy.
Clone troopers turned against the Jedi, forcing Ahsoka and Rex to flee. The Republic transformed into the Galactic Empire shortly afterward.
Imperial Occupation
Under Imperial rule, Mandalore lost much of its remaining autonomy. The Empire exploited beskar resources and installed loyal governors to maintain control. Resistance movements formed among surviving clans.
Mandalorian artist and engineer Sabine Wren later became a major figure in anti-Imperial operations. She helped unite several clans using the legendary Darksaber, an ancient weapon symbolizing leadership among Mandalorians.
The Great Purge
The Empire eventually launched a catastrophic military campaign known as the Great Purge. Imperial forces deployed advanced weaponry and systematically targeted Mandalorian strongholds.
Large portions of Mandalore became uninhabitable. Surviving Mandalorians scattered throughout the galaxy, hiding their identities and preserving fragments of their culture in exile.
Key Individuals
  - Satine Kryze - Pacifist Duchess of Mandalore
  - Bo-Katan Kryze - Resistance leader and later claimant to Mandalorian leadership
  - Pre Vizsla - Leader of Death Watch
  - Maul - Former Sith apprentice who briefly ruled Mandalore
  - Sabine Wren - Rebel operative and Mandalorian weapons expert
  - Din Djarin - Mandalorian bounty hunter associated with a surviving orthodox sect
Important Concepts
  - Beskar: Rare metal used in Mandalorian armor
  - Darksaber: Symbolic black-bladed lightsaber tied to leadership
  - The Way of the Mandalore: Cultural code followed by some Mandalorian groups
  - Clan Structure: Family-based political and military organization system
  - Foundlings: Adopted children raised within Mandalorian culture"""

print(f"Len: {len(text)}")
chunks = chunk_markdown(text)
print(f"Number of chunks: {len(chunks)}")
for i, c in enumerate(chunks):
    print(f"Chunk {i} len: {len(c)}")
