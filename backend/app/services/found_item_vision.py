"""Two-view Qwen prompt and Ollama request construction for found items."""

import json
from typing import Any

FOUND_ITEM_ANALYSIS_PROMPT = """
Analyze all supplied photographs as different views of the same reported
lost item. Combine the evidence into exactly one JSON object. Do not count
the same object or component more than once merely because it appears in
multiple views.

Exactly two images are supplied:
1. Full front view.
2. Full back view.

You must inspect every image separately before combining the results. Include
view_observations with exactly two entries. Each entry must state the image
number, visible region, image quality, and any independently observed damage.

If fewer than two views can be examined, set needs_review to true. Never claim
that a surface has no visible damage when that surface is hidden, blurry,
overexposed, too small, or outside the image.

Prioritize physical geometry over color. Inspect the silhouette, surface
curvature, highlight continuity, shadows, and symmetry. A localized inward
curve, flattened area, or repeated contour irregularity visible from multiple
angles must be reported as a dent.

Perform the following inspection internally before producing the JSON:

1. VIEW CONSISTENCY
Determine whether all photographs show the same physical item. Compare its
shape, color, markings, attachments, damage, and component placement.

2. OBJECT IDENTIFICATION
Identify the item using:
- generic_name: the common general name, such as "water bottle".
- object_name: a specific everyday description supported by visible evidence.
- alternative_names: other common names someone might search for.
Use visible non-sensitive product names and model markings when legible.
Do not invent a brand, model, material, or feature.

PRIMARY ITEM AND CONTENTS
Identify the complete physical item being handed in, not merely the most
readable object inside it. Describe a wallet as a wallet whether it is closed
or open: include its supported color, visible material or style, compartments
or card slots, and condition just as for any other ordinary item. If an ID is
clearly visible inside, only add that the wallet contains the specific type of
ID; do not replace the wallet description with the ID, and do not include the
ID owner's name in the wallet summary. Set document_kind for the contained ID
so it can be handled as sensitive. Ordinary cards in a wallet are not
necessarily IDs; do not call them IDs unless their type is recognizable.
Never copy ID numbers, addresses, signatures, or other private document text.
If the ID is loose and no wallet or other holder is the main item, identify
the ID as the primary item instead and follow the ID-specific name rule below.
Apply the same primary-item reasoning to other containers and their visible
contents without inventing hidden contents.

PHONE WALLPAPER (only when the item is a phone with a visible, lit screen)
Inspect the wallpaper image separately from lock-screen text and controls. If
the wallpaper scene is clearly visible, describe its recognizable visual
content briefly in distinctive_features and extraction_summary, including a
person's clothing or the background when useful for recognizing this phone.
Describe appearance only; never identify a person or infer who they are.
Do not copy the clock, date, notifications, messages, numbers, or other personal
screen text. If the wallpaper is obscured or unclear, do not guess. This
instruction does not apply to items without a visible phone screen and does
not replace the ordinary item identification or condition inspection.

3. COMPONENT COUNTING
Count unique primary objects and visible functional components. A component
seen in several views must be counted only once. If a component is hidden or
overlapping, provide the minimum clearly visible count and mark it as an
estimate.

4. MANDATORY CONDITION INSPECTION
Inspect every visible surface before assigning the overall condition.

For every visible component, examine:
- the outer silhouette and contour;
- symmetry and normal geometry;
- changes in reflections, highlights, and shadows;
- inward or outward deformation;
- flattened, compressed, bent, or warped areas;
- scratches, scuffs, chips, cracks, stains, discoloration, and missing parts;
- wear around edges, corners, lids, handles, straps, screens, and connectors.

For rigid bottles and similar containers, specifically inspect:
- the neck and shoulder immediately below the lid;
- the complete left and right side walls;
- the front and rear body surfaces;
- the bottom edge and base.

A localized inward curve, flattened section, distorted contour, or interruption
in an otherwise continuous surface highlight may indicate a dent. If the same
deformation is supported by more than one view, report it as confirmed visible
damage. If it appears in only one view and could be lighting or reflection,
report it as uncertain or probable damage.

Do not state "no visible damage" merely because the item's color looks smooth.
Use "no_visible_damage" only when the relevant surface is clearly shown at
sufficient size, focus, and lighting. Otherwise use "not_assessable".

For every surface assessment:
- status must be "visible_damage", "no_visible_damage", or "not_assessable".
- damage_types must list specific observed damage such as "dent", "scratch",
  "scuff", "crack", "chip", "stain", "bending", or "discoloration".
- location must identify where the damage appears.
- severity must be "minor", "moderate", "severe", or null.
- certainty must be "confirmed", "probable", or "uncertain".
- evidence must describe the visible observation, not an unsupported conclusion.

Overall condition:
- "new": no observable use or wear.
- "good": intact with no damage or only minor cosmetic wear.
- "fair": visible dent, deformation, or moderate wear, but still generally intact.
- "poor": broken, severely damaged, or missing important components.
- "unknown": the condition cannot be assessed reliably.

5. MATERIAL INSPECTION
Return material as a flat JSON array of short strings, never as an object. When
the component matters, include it in the string, for example "body: coated
metal" or "lid: plastic". If material cannot be confirmed visually, describe it
as likely or leave the array empty rather than claiming certainty.

Return every one of these fields:
views_consistent, generic_name, object_name, alternative_names, object_count,
component_counts, count_is_estimate, count_confidence, counting_notes,
category, subcategory, document_kind, document_owner_name, colors, material, brand, model_or_variant,
visible_markings, functional_components, condition, condition_visibility,
condition_confidence, surface_assessments, condition_details, patterns,
distinctive_features, likely_use, short_description, confidence, needs_review,
uncertainty_notes, extraction_summary, received_view_count, view_observations.

Data requirements:
- views_consistent, count_is_estimate, and needs_review: boolean.
- object_count: integer.
- alternative_names, colors, material, visible_markings,
  functional_components, condition_details, patterns, distinctive_features,
  counting_notes, and uncertainty_notes: arrays of strings.
- Every entry in condition_details must be a string, never an object.
- generic_name, object_name, category, subcategory, condition_visibility,
  likely_use, short_description, and extraction_summary: single strings, never
  arrays or objects.
- component_counts: array of objects with component, count, and
  count_is_estimate.
- surface_assessments: array of objects with component, status, damage_types,
  location, severity, certainty, and evidence.
- count_confidence, condition_confidence, and confidence:
  "high", "medium", or "low".
- brand and model_or_variant: string or null.
- document_kind: "none", "school ID", "driver's license", "government ID",
  "passport", "bank card", "identification card", or "sensitive document".
- document_owner_name: only the complete, clearly readable printed owner's
  name on an ID, or null. Never guess a name or copy other private text.
- extraction_summary: concise searchable summary containing the supported
  item type and name, count, colors, visible brand and model (if any),
  materials, markings, distinctive features, damage and its location,
  condition, and important uncertainty. Do not omit a known searchable detail
  or invent one to make the summary sound complete. Never leave this field
  empty, even for a plain wallet; describe the visible item itself.
- received_view_count: integer.
- view_observations: array of objects containing image_index, visible_region,
  image_quality, damage_observations, and notes. damage_observations and notes
  must each be arrays of strings.

Privacy rules:
Do not perform facial recognition. If either image shows an ID or another
sensitive document, set document_kind even when the document is inside a
holder or rotated sideways. When the ID itself is the primary item, inspect
the printed name field in both views. If the complete owner's name is clearly
readable, put only that name in document_owner_name, including when printed
in a "LAST, FIRST MIDDLE" layout. For an ID inside a wallet, set
document_owner_name to null; the wallet summary only states the ID type.
If any name part is unreadable or ambiguous, use null; do not guess from a
face, school, issuer, or other context. Never
copy numbers, addresses, signatures, barcodes, contact details, or other
private document text into ANY field. These rules apply to documents only;
for ordinary items, retain every supported detail required above.
Non-sensitive product branding and model markings on ordinary objects may be
reported.

Return only one valid JSON object. Do not return Markdown, commentary, or the
internal inspection process.
""".strip()


FOUND_ITEM_DAMAGE_AUDIT_PROMPT = """
Inspect only the physical condition of the same item in these two views. Do
not identify its brand, model, owner, or intended use. Examine each image
independently, then compare them.

Scan the neck and shoulder, upper/middle/lower left and right body walls,
front and rear surfaces, base, lid, handle, edges, corners, straps, screens,
and connectors when present. Look for inward curvature, flattened areas,
asymmetry, interrupted highlights, contour changes, dents, deformation,
bending, warping, scratches, scuffs, cracks, chips, stains, discoloration,
and missing or broken parts. Do not assume smooth color means undamaged.

Report only observations directly supported by pixels:
- observations contains physical defects. Each observation must have one or
  more specific damage_types, an exact location, the supporting image numbers,
  severity, certainty, and concrete visual evidence.
- clear_regions contains a no-damage assessment only for a specifically named
  region that is clearly visible at useful size, focus, angle, and lighting.
  Its evidence must describe the visible contour or surface continuity that
  supports the assessment; merely saying "no damage" is not evidence.
- not_assessable_regions contains every inspected region that is hidden,
  cropped, blurry, too small, overexposed, or ambiguous. Give the image numbers
  and reason. A not-assessable region is never evidence of no damage.

Combine repeated views of the same defect into one observation. Use confirmed
only for an unambiguous visible defect, probable when supported but potentially
affected by angle or lighting, and uncertain when it is only a possibility.
Set damage_present true exactly when observations is non-empty. Do not assign
an overall item condition; the server derives it from the evidence.

Return only one valid JSON object matching the supplied schema. Do not return
Markdown, commentary, identity details, or internal reasoning.
""".strip()


def request_found_item_analysis(
    front_image: bytes,
    back_image: bytes,
    *,
    client,
    model: str,
    response_format: dict[str, Any],
    repair_instruction: str = "",
):
    """Send two ordered item views to Ollama using the found-item prompt."""
    # Explicit, separated markers prevent some vision models from treating two
    # same-sized images as adjacent frames of one video.
    content = (
        "IMAGE 1 - FRONT VIEW:\n"
        "[img]\n"
        "END IMAGE 1.\n\n"
        "IMAGE 2 - BACK VIEW:\n"
        "[img]\n"
        "END IMAGE 2.\n\n"
        + FOUND_ITEM_ANALYSIS_PROMPT
    )
    if repair_instruction:
        content += "\n\n" + repair_instruction

    return client.chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": content,
                "images": [front_image, back_image],
            }
        ],
        format=response_format,
        think=False,
        stream=False,
        options={
            "temperature": 0,
            "num_ctx": 12288,
            "num_predict": 3072,
        },
    )


def request_found_item_damage_audit(
    front_image: bytes,
    back_image: bytes,
    *,
    client,
    model: str,
    response_format: dict[str, Any],
    repair_instruction: str = "",
):
    """Run the compact condition-only pass over the same ordered views."""
    content = (
        "IMAGE 1 - FRONT VIEW:\n"
        "[img]\n"
        "END IMAGE 1.\n\n"
        "IMAGE 2 - BACK VIEW:\n"
        "[img]\n"
        "END IMAGE 2.\n\n"
        + FOUND_ITEM_DAMAGE_AUDIT_PROMPT
        + "\n\nRequired JSON Schema:\n"
        + json.dumps(response_format, separators=(",", ":"))
    )
    if repair_instruction:
        content += "\n\n" + repair_instruction

    return client.chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": content,
                "images": [front_image, back_image],
            }
        ],
        format=response_format,
        think=False,
        stream=False,
        options={
            "temperature": 0,
            "num_ctx": 8192,
            "num_predict": 1200,
        },
    )
