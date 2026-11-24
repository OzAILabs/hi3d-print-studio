# Pictures that print well

Hi3D Studio builds the 3D model from **one picture**, so the picture decides most of the result.
A flat 2D cartoon (black outlines, flat fills, thin limbs) gives the shape model nothing to read
depth from. A photo or render of something that already looks like a **physical figurine** works.

## Rules of thumb

| Rule | Why |
|---|---|
| One compact subject on a round base | One solid piece with a flat bottom for the build plate |
| Chunky forms, nothing thin or floating | Thin spikes and loose parts break or vanish in the mesh |
| No capes, flowing cloth or banners | Thin draped parts come out as hollow shells with windows |
| Weapons resting on the base, close to the body | Otherwise they become fragile spikes |
| **Exactly as many solid colours as you have filaments** (e.g. 4), in large areas | Fewer, larger colour regions = far fewer filament changes = much shorter prints |
| No gradients, weathering, dry-brushing or fine patterns | Painted shading turns into extra colour speckle |
| Soft, even, front light; almost no shadows | Shadows get read as extra colours |
| Whole figure visible with a margin, plain contrasting backdrop | Clean background removal; the shape model sees the full silhouette |
| Square 1:1, front view turned ~15° | Matches what the shape model expects |

## Example: Frog Knight (easy, ~21 h print, 640 colour changes)

```
A studio product photograph of a single collectible vinyl figurine: a chubby, cheerful frog knight standing upright on a round, flat display base. The figure is compact and clearly taller than it is wide, with chunky rounded proportions: a big head, thick short arms and legs, wide flat feet, no thin or spindly parts, and nothing floating or sticking far out from the body.

He wears a simple rounded helmet with a short thick crest, a smooth chest plate, and holds a short, thick wooden sword close to his body. A small round shield is strapped to his other arm, pressed against his side.

The figurine is painted in exactly four bold, solid, matte colours with large clean colour areas: bright green skin, golden-yellow armour, dark brown sword, belt and base, and cream-white belly and eyes. No gradients, no tiny patterns, no outlines, no text, no fine painted details. The paint looks like a smooth factory-painted toy.

The full figure is centered and completely visible from the bottom of the base to the top of the helmet, with a small margin on all sides and nothing cropped. Straight-on front view, very slightly turned (about 15 degrees), camera at chest height, 85 mm lens, sharp focus throughout. Soft, even, diffuse studio lighting from the front with almost no shadows on the figure and no strong highlights. Plain light grey seamless studio backdrop, clearly different from the figure's colours. Square 1:1 image, high resolution.
```

## Example: Orc Warlord (detailed, epic fantasy)

```
A studio product photograph of a single highly detailed collectible statue of a hulking orc warlord, menacing and battle-scarred, standing in a wide, heavy stance on a round display base shaped like a slab of cracked dark stone with a broken helmet and a few skulls half-buried in rubble at his feet. The statue is compact, solid and clearly taller than it is wide.

He has a massive hunched frame, thick muscular arms and short thick legs, a heavy jaw with jutting tusks, a scarred face with a snarl, and small deep-set eyes. He wears a horned iron helmet with short, thick, curved horns, layered heavy plate armour on the shoulders and chest with large rivets and jagged edges, a thick spiked belt, and a heavy leather war-skirt that hangs close to the legs. He grips a huge single-bladed war axe with both hands, its thick head resting on the base in front of him, the haft held close to his body. Everything is sculpted thick and chunky: no thin spikes, no loose chains, no capes, no flowing cloth, no banners, nothing floating or sticking far out from the body.

The statue is painted in exactly four solid matte colours with large clean colour areas: dark sickly green skin, dark iron-grey armour, helmet and axe head, rust-red leather and belt, and bone-ivory tusks, horns and skulls. The stone base is the same iron-grey as the armour. No gradients, no weathering, no dry-brushing, no tiny painted patterns, no outlines, no text.

The full statue is centered and completely visible from the bottom of the base to the tips of the helmet horns, with a small margin on all sides and nothing cropped. Straight-on front view, turned very slightly (about 15 degrees), camera at chest height, 85 mm lens, sharp focus throughout. Soft, even, diffuse studio lighting from the front with almost no shadows on the statue and no strong highlights, a subtle rim light to separate the dark statue from the backdrop. Plain light grey seamless studio backdrop. Square 1:1 image, high resolution.
```

Swap the subject paragraph and the colour line for your own idea and keep the rest.
The dragon in the hero shots is a hand-painted picture: detailed, shaded art works too, but
its shading becomes extra colour changes (~39 h print vs ~21 h for the frog).
