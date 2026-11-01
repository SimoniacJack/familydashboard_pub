# Meal Planning Rules

## Location & Units
- This family lives in the UK. Use UK English throughout.
- All weights must use metric: grams (g), kilograms (kg), millilitres (ml), litres (l).
- Use tablespoons (tbsp) and teaspoons (tsp) for small volumes only.
- Never use cups, ounces, pounds, or Fahrenheit.
- Oven temperatures in degrees Celsius (°C).

## Ingredients
- All ingredients must be readily available in standard UK supermarkets (Tesco, Sainsbury's, Asda, Morrisons, Waitrose).
- Use UK naming conventions: e.g. "courgette" not "zucchini", "aubergine" not "eggplant", "coriander" not "cilantro", "plain flour" not "all-purpose flour", "spring onion" not "scallion", "rocket" not "arugula", "minced beef" not "ground beef", "beef mince" is acceptable.
- Do not suggest ingredients that require specialist shops or online ordering.

## Meal suitability
- Meals must work for the whole family including Ada (age 7, picky — plain and simple food, no strong flavours or spices) and Kit (age 1, toddler — soft foods, no choking hazards, low salt).
- Prefer meals where adult portions can be mildly seasoned and children's portions kept plainer.

## Prep time
- Every meal must include an estimated prep + cook time in minutes as a single integer field "prep_minutes".
- Consider the day of the week: on weekdays suggest quicker meals (under 45 minutes). On weekends longer or more elaborate meals are fine.
- If calendar events are provided for a day, factor in the family's schedule — busy days should have very quick or make-ahead meals.

## Variety
- Do not repeat the same meal within the same week.
- Vary proteins across the week (don't serve chicken every day).
- Include at least one vegetarian dinner per week.
- Include at least one fish or seafood meal per week.

## Calendar awareness
- If a calendar event is provided for a slot's day, consider it when choosing the meal.
- Events like "football", "swimming", or "after-school club" suggest a quick weeknight dinner is needed.
- Events like "family visit" or "birthday" suggest something more special or crowd-pleasing.
- "Date night" or similar suggests children may be eating separately — simpler kids' meal is fine.
