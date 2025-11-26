from Solver.bom import get_bom_engine

engine = get_bom_engine()

targets = [
    'Unsolvable puzzle cube',
    'Eggceptional lunar totem', 
    'Beggspoke Demeters necklace',
    'Brilliant tungsten ankh',
    'Jeweled gusset',
    'Clairvoyant interstellar compass',
    'Reggreference quantum metronome'
]

all_ingredients = set()

def get_all_ingredients_recursive(artifact_id, visited=None):
    if visited is None:
        visited = set()
    if artifact_id in visited:
        return set()
    visited.add(artifact_id)
    
    recipe = engine.get_recipe(artifact_id)
    if not recipe:
        return set()
    
    result = set()
    for ing_id, ing_name, count in recipe.ingredients:
        name = engine.id_to_name(ing_id)
        result.add(name)
        result.update(get_all_ingredients_recursive(ing_id, visited))
    return result

for target in targets:
    tid = engine.name_to_id(target)
    if tid:
        ings = get_all_ingredients_recursive(tid)
        all_ingredients.update(ings)
        print(f'{target}:')
        for ing in sorted(ings):
            print(f'  {ing}')
        print()

print('=== ALL INGREDIENTS (including mid-tier) ===')
for name in sorted(all_ingredients):
    print(f'  "{name}"')
