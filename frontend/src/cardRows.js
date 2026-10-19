// Keep cards without versions visible so their first version can be created.
export function cardRows(cards) {
  return cards.flatMap(card => {
    const versions = card.versions.length ? card.versions : [null];
    return versions.map(version => ({
      ...(version || {id: null, recipes: [], inspections: []}),
      key: version ? `version-${version.id}` : `card-${card.id}`,
      code: card.code,
      name: card.name,
      card_id: card.id,
      card_name: card.name,
    }));
  });
}
