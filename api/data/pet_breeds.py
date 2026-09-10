# Espelha literalmente as listas inline de billy_app/lib/screens/add_pet_screen.dart
# (_dogBreeds / _catBreeds) — fonte de verdade é o app, duplicada aqui até existir
# um jeito compartilhado de validar Dart + Python.

DOG_BREEDS = [
    "SRD / Não sei",
    "Labrador",
    "Golden Retriever",
    "Bulldog Francês",
    "Poodle",
    "Shih Tzu",
    "Yorkshire",
    "Beagle",
    "Pastor Alemão",
    "Rottweiler",
    "Pit Bull",
    "Lhasa Apso",
    "Maltês",
    "Dachshund",
    "Husky Siberiano",
    "Border Collie",
]

CAT_BREEDS = [
    "SRD / Não sei",
    "Persa",
    "Siamês",
    "Maine Coon",
    "Ragdoll",
    "Bengal",
    "Angorá",
    "Scottish Fold",
    "Sphynx",
    "Abissínio",
    "Birmanês",
]

BREEDS_BY_SPECIES = {
    "dog": DOG_BREEDS,
    "cat": CAT_BREEDS,
}
