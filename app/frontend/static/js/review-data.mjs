// Counts use the same records as the drawer. Linked questions already belong
// to a finding; standalone questions add their own item to "All".
export function reviewCounts(view, types) {
  const hidden = new Set(view.hidden_finding_ids || []);
  const places = view.standalone_questions || [];
  const counts = { questions: view.questions.length + places.length };
  for (const type of types) {
    counts[type] = view.findings.filter(f => f.type === type && !hidden.has(f.finding_id)).length;
  }
  counts.all = types.reduce((sum, type) => sum + counts[type], 0) + places.length;
  return counts;
}

export function standaloneQuestions(view, filter, preferences) {
  return preferences.show_questions && (filter === 'all' || filter === 'questions')
    ? view.standalone_questions || [] : [];
}
