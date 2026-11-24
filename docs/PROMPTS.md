# Prompts that print well

Hi3D Print Studio builds the 3D model from **one picture**, so the picture decides most of the result.
A flat 2D cartoon (black outlines, flat fills, thin limbs) gives the shape model nothing to read
depth from. A photo-like render of something that already looks like a **physical figurine** works.

Use any image generator (ChatGPT, Gemini, Midjourney, FLUX, Qwen-Image...). The prompt below is
built from blocks: some keep the picture printable and should stay as they are, the rest are
slots you replace with your own idea.

## The template

Copy it, replace the `[SLOTS]`, keep everything else.

```
A studio product photograph of a single collectible [MATERIAL] figurine of [SUBJECT], standing on a round, flat display base [BASE DETAIL]. The figure is compact, solid and clearly taller than it is wide, with chunky proportions: [BODY SHAPE], no thin or spindly parts, nothing floating or sticking far out from the body.

[POSE AND PROPS]. Everything is sculpted thick and chunky: no thin spikes, no loose chains, no capes, no flowing cloth, no banners.

The figure is painted in exactly [N] solid matte colours with large clean colour areas: [COLOUR 1 + WHERE], [COLOUR 2 + WHERE], [COLOUR 3 + WHERE] and [COLOUR 4 + WHERE]. No gradients, no weathering, no dry-brushing, no tiny painted patterns, no outlines, no text.

The full figure is centered and completely visible from the bottom of the base to the top of [HIGHEST POINT], with a small margin on all sides and nothing cropped. Straight-on front view, turned very slightly (about 15 degrees), camera at chest height, 85 mm lens, sharp focus throughout. Soft, even, diffuse studio lighting from the front with almost no shadows on the figure and no strong highlights[RIM LIGHT]. Plain [BACKDROP] seamless studio backdrop, clearly different from the figure's colours. Square 1:1 image, high resolution.
```

## What to keep, what to replace

| Block | Keep or replace | Why it's there |
|---|---|---|
| "studio product photograph of a single collectible ... figurine" | **Keep** (swap `[MATERIAL]`) | Makes the generator draw a physical object with real depth, not a flat illustration |
| `[MATERIAL]` | Replace | Sets the surface look: `vinyl` (smooth, toy-like), `resin` (detailed statue), `clay` (soft, rounded), `wooden` (carved) |
| `[SUBJECT]` | **Replace** | Your idea: one character or object |
| "round, flat display base" | **Keep** | Gives the print a flat bottom to sit on the build plate |
| `[BASE DETAIL]` | Replace or delete | e.g. `shaped like cracked stone with a few skulls`, `covered in moss`; delete for a plain disc |
| "compact ... taller than it is wide, chunky proportions" | **Keep** | Fills a square frame; thick parts survive meshing and printing |
| `[BODY SHAPE]` | Replace | e.g. `a big head, thick short arms and legs, wide flat feet` |
| `[POSE AND PROPS]` | **Replace** | What it holds and wears. Keep props **resting on the base or pressed against the body** |
| "no thin spikes ... no capes, no flowing cloth" | **Keep** | Thin, draped parts come out as hollow shells or break off |
| "exactly [N] solid matte colours" | **Keep**, set `[N]` | `[N]` = your filament count (the studio's "Filament colours"). The studio reads these colours straight from the picture |
| `[COLOUR ... + WHERE]` | **Replace** | Name each colour and where it goes. See the colour tips below |
| "no gradients, weathering, dry-brushing, patterns, outlines, text" | **Keep** | Painted shading and grime become extra colour speckle and many more filament changes |
| "full figure visible ... nothing cropped" | **Keep** (set `[HIGHEST POINT]`) | The shape model needs the whole silhouette |
| "front view, ~15 degrees, chest height, 85 mm" | **Keep** | Matches what the shape model expects |
| "soft, even, diffuse light, almost no shadows" | **Keep** | Shadows get read as extra colours |
| `[RIM LIGHT]` | Add for dark figures | `, a subtle rim light to separate the dark figure from the backdrop` |
| `[BACKDROP]` | Replace | `light grey` for most figures; `dark charcoal` for very light figures |
| "Square 1:1, high resolution" | **Keep** | Square input works best |

## Colour tips

- **Match the count.** Ask for exactly as many colours as you have filaments (an AMS lite has 4). Fewer colours = fewer filament changes = a much shorter print.
- **Make every colour clearly different in hue,** not just lighter or darker: `bright green`, `golden yellow`, `dark brown`, `cream`, not `light green` + `dark green`. Shades of one colour get merged into one filament.
- **Small accents are fine** if they're a distinct colour: ivory horns or gold trim keep their own filament even when they cover only 2% of the figure.
- **Name where each colour goes,** so the generator doesn't sprinkle it everywhere: `rust-red leather skirt and axe handle`.
- **For 2 or 3 colours,** drop the extra `[COLOUR]` entries and change "exactly four" to "exactly two" or "exactly three".

## Examples

Each one uses the template unchanged except for the slots. The frog and orc are in the gallery in the README.

### Frog Knight (vinyl toy, 4 colours) — ~15 min to print file, ~21 h print

```
A studio product photograph of a single collectible vinyl figurine of a chubby, cheerful frog knight, standing on a round, flat display base. The figure is compact, solid and clearly taller than it is wide, with chunky proportions: a big head, thick short arms and legs, wide flat feet, no thin or spindly parts, nothing floating or sticking far out from the body.

He wears a simple rounded helmet with a short thick crest and a smooth chest plate, and holds a short, thick wooden sword close to his body; a small round shield is strapped to his other arm, pressed against his side. Everything is sculpted thick and chunky: no thin spikes, no loose chains, no capes, no flowing cloth, no banners.

The figure is painted in exactly four solid matte colours with large clean colour areas: bright green skin, golden-yellow armour, dark brown sword, belt and base, and cream-white belly and eyes. No gradients, no weathering, no dry-brushing, no tiny painted patterns, no outlines, no text.

The full figure is centered and completely visible from the bottom of the base to the top of the helmet, with a small margin on all sides and nothing cropped. Straight-on front view, turned very slightly (about 15 degrees), camera at chest height, 85 mm lens, sharp focus throughout. Soft, even, diffuse studio lighting from the front with almost no shadows on the figure and no strong highlights. Plain light grey seamless studio backdrop, clearly different from the figure's colours. Square 1:1 image, high resolution.
```

### Orc Warlord (detailed resin statue, 4 colours, dark figure)

```
A studio product photograph of a single collectible resin figurine of a hulking, menacing, battle-scarred orc warlord, standing on a round, flat display base shaped like a slab of cracked dark stone with a broken helmet and a few skulls half-buried in rubble. The figure is compact, solid and clearly taller than it is wide, with chunky proportions: a massive hunched frame, thick muscular arms, short thick legs, a heavy jaw with jutting tusks, no thin or spindly parts, nothing floating or sticking far out from the body.

He wears a horned iron helmet with short, thick, curved horns, layered heavy plate armour on the shoulders and chest with large rivets, a thick spiked belt and a heavy leather war-skirt that hangs close to the legs; he grips a huge single-bladed war axe with both hands, its thick head resting on the base in front of him. Everything is sculpted thick and chunky: no thin spikes, no loose chains, no capes, no flowing cloth, no banners.

The figure is painted in exactly four solid matte colours with large clean colour areas: dark sickly green skin, dark iron-grey armour, helmet, axe head and stone base, rust-red leather skirt, belt and axe handle, and bone-ivory tusks, horns and skulls. No gradients, no weathering, no dry-brushing, no tiny painted patterns, no outlines, no text.

The full figure is centered and completely visible from the bottom of the base to the tips of the helmet horns, with a small margin on all sides and nothing cropped. Straight-on front view, turned very slightly (about 15 degrees), camera at chest height, 85 mm lens, sharp focus throughout. Soft, even, diffuse studio lighting from the front with almost no shadows on the figure and no strong highlights, a subtle rim light to separate the dark figure from the backdrop. Plain light grey seamless studio backdrop, clearly different from the figure's colours. Square 1:1 image, high resolution.
```

### Slot swaps for other figures

Paste these into the template's slots. Untested ideas, written to the same rules.

**Round little robot (vinyl, 4 colours)**
- `[SUBJECT]` a round little friendly robot
- `[BODY SHAPE]` a dome-shaped head, a barrel body, stubby thick arms and short legs with wide feet
- `[POSE AND PROPS]` He waves with one stubby hand raised close to his head and holds a small thick wrench against his chest
- `[COLOURS]` glossy red body, white head and hands, dark grey arms, legs and base, and light blue eyes and chest panel

**Baby dragon on a rock (clay, 4 colours)**
- `[SUBJECT]` a chubby baby dragon sitting up
- `[BASE DETAIL]` with a rounded boulder on it that the dragon sits on
- `[BODY SHAPE]` a big round head, a round belly, short thick legs and a thick tail curled around the boulder
- `[POSE AND PROPS]` Its two small wings are folded flat against its back and it hugs a large round egg against its belly
- `[COLOURS]` purple scales, orange belly and wing membranes, cream egg and horns, and dark brown boulder and base

**Wizard gnome (resin, 4 colours)**
- `[SUBJECT]` a stout old gnome wizard
- `[BODY SHAPE]` a large round nose, a thick bushy beard that reaches his belt, short thick legs and big boots
- `[POSE AND PROPS]` He wears a tall, slightly bent pointed hat and a robe that falls straight to the base, and holds a short thick staff upright against his side, its foot resting on the base
- `[COLOURS]` deep blue hat and robe, white beard and eyebrows, tan skin and staff, and dark brown boots, belt and base

**Treasure-chest mimic (resin, 3 colours, dark figure)**
- Change "figurine of" to "sculpture of", and "exactly four" to "exactly three"
- `[SUBJECT]` a grinning treasure-chest monster with its lid open
- `[BODY SHAPE]` a squat wooden chest body, a wide open mouth with thick rounded teeth and a thick tongue
- `[POSE AND PROPS]` A few thick gold coins sit piled in its mouth and on the base in front of it
- `[COLOURS]` dark brown wood, gold metal bands, coins and lock, and ivory teeth with a red tongue
- `[RIM LIGHT]` add the rim light

**Space cat (vinyl, 4 colours)**
- `[SUBJECT]` a chubby cat astronaut
- `[BODY SHAPE]` a big round helmeted head with the face visible, a round body, short thick limbs
- `[POSE AND PROPS]` The round helmet visor is open and pushed up; the cat holds a small thick flag pole against its chest, the flag folded tight around the pole
- `[COLOURS]` white space suit, orange fur on the face and paws, dark grey boots, gloves and base, and light blue visor and suit panels

## Things that usually go wrong

| Avoid | What happens | Instead |
|---|---|---|
| Flat 2D cartoons, line art, logos | No depth: the shape comes out flat or warped | Ask for a figurine or statue photo |
| Capes, banners, flowing hair or robes that flare out | Thin hollow shells with windows | Cloth that hangs straight to the base, hair as solid shapes |
| Swords, spears, staffs held out from the body | Spikes that break off or vanish | Weapons resting on the base or held against the body |
| Two or more characters | They fuse into one odd mesh | One subject per picture |
| Dramatic lighting, strong shadows, painted shading | Shadows read as extra colours; many more filament changes | Soft, even front light |
| Light + dark shades of one colour as separate paints | They merge into one filament | Different hues |
| Named characters from films, games or comics | Copyright, and the generator may refuse | Describe your own original character |

The dragon in the README is a hand-painted picture: detailed shaded art works too, but its shading
becomes extra colour changes (~39 h print vs ~21 h for the flat-coloured frog).
