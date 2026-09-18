const VERDICTS = [
  {
    level: 'GREEN',
    name: 'No red flags',
    short: 'Every product is registered for the crop, the waiting time before harvest is over, and no EU limit blocks it.',
    todo: 'Keep the spray log with the lot. The rules check legal limits, not a lab measurement.',
  },
  {
    level: 'AMBER',
    name: 'Check before shipping',
    short: 'Shippable, but something needs a look: a limit that just dropped or drops before arrival, or a substance allowed only by import tolerance.',
    todo: 'Read the warning, keep doses at label rates, and consider a residue test for a sensitive buyer.',
  },
  {
    level: 'CANNOT_VERIFY',
    name: 'Cannot verify',
    short: 'Something could not be confirmed from an official source: an unknown product name, a crop missing from the label, or no EU limit for this crop.',
    todo: 'Fix the name (tap a suggestion) or check the label. The tool never guesses, so it will not call the lot safe.',
  },
  {
    level: 'RED',
    name: 'Not safe to ship',
    short: 'A rule is broken: a limit at the detection level, a product not registered for the crop, or harvest before the waiting time ends.',
    todo: 'Follow the steps under the verdict: a later harvest date, a residue test, or a safer product for the next spray.',
  },
] as const

const GLOSSARY = [
  {
    term: 'MRL (maximum residue limit)',
    text: 'The highest amount of a pesticide allowed on a food in the EU, in mg per kg. Set per substance and per crop by EU regulation, and checked at the border.',
  },
  {
    term: 'Limit at the detection level (0.01* mg/kg)',
    text: 'A star means the limit sits at the lowest level labs can measure. In practice any detectable residue fails. This is common for substances no longer approved in the EU.',
  },
  {
    term: 'Pre-harvest interval (DAR)',
    text: "Days to wait between the last spray and harvest, printed on the product's Moroccan label for each crop. Harvest earlier and the residue may still be high.",
  },
  {
    term: 'ONSSA register',
    text: "Morocco's official list of authorised pesticide products (ONSSA), with their active substances, the crops they are registered for and the waiting times.",
  },
  {
    term: 'Import tolerance',
    text: 'An EU limit set for imported food even though the substance may not be used in the EU. Legal, but closely watched.',
  },
  {
    term: 'RASFF',
    text: "The EU's rapid alert system for food. Every rejected lot is published there; the rules in this tool were back-tested on 564 real pesticide notifications.",
  },
]

export function VerdictLegend({ compact = false }: { compact?: boolean }) {
  return (
    <ul className={compact ? 'legend compact' : 'legend'}>
      {VERDICTS.map((v) => (
        <li key={v.level} className={`legend-item v-${v.level}`}>
          <span className="legend-dot" aria-hidden="true" />
          <div>
            <strong>{v.name}</strong>
            {!compact && <p>{v.short}</p>}
            {!compact && (
              <p className="todo">
                <span>What to do:</span> {v.todo}
              </p>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}

export function Guide() {
  return (
    <section className="guide" id="guide">
      <div className="section-head reveal">
        <p className="eyebrow dark">Guide</p>
        <h2>Reading your result</h2>
        <p>Four possible verdicts. The worst finding on any product decides the verdict for the whole lot.</p>
      </div>
      <div className="reveal">
        <VerdictLegend />
      </div>

      <div className="guide-grid">
        <div className="reveal">
          <h3>Tips for a good check</h3>
          <ul className="tips">
            <li>
              <strong>Write the trade name as on the label</strong>, for example <code>ACTARA 25 WG</code>. Type three letters to see names from
              the register.
            </li>
            <li>
              <strong>Include every spray of the season</strong>, not just the last one. Old sprays can still leave residues when the limit is
              at the detection level.
            </li>
            <li>
              <strong>Use the date you plan to harvest.</strong> The EU limit is checked on the arrival date, 10 days later.
            </li>
            <li>
              <strong>A spray planned for next week?</strong> Enter it with its future date: you get safer products to use instead.
            </li>
            <li>
              <strong>Already have a spreadsheet?</strong> Use "Paste from a spreadsheet" with one line per spray: name, date.
            </li>
          </ul>
        </div>
        <div className="reveal">
          <h3>Words you will see</h3>
          <div className="glossary">
            {GLOSSARY.map((g) => (
              <details key={g.term}>
                <summary>{g.term}</summary>
                <p>{g.text}</p>
              </details>
            ))}
          </div>
        </div>
      </div>

      <p className="disclaimer reveal">
        ResidueCheck supports the decision; it does not replace a residue analysis by an accredited laboratory or your buyer's requirements.
        Covered today: products registered in Morocco, 32 export crops, destination European Union.
      </p>
    </section>
  )
}
