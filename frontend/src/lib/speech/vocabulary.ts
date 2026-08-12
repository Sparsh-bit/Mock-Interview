/**
 * Correcting what the recogniser heard — lib/speech/vocabulary.ts
 *
 * THE PROBLEM THIS SOLVES. The Web Speech API has no way to supply a custom
 * vocabulary. It is a general-purpose recogniser optimised for everyday English,
 * so every technical term in an answer is a coin flip: "HashMap" comes back as
 * "hash map", "JVM" as "jvm" or "j v m", "polymorphism" as "poly morphism". A
 * candidate says the right thing and the transcript records the wrong thing —
 * which then gets scored, quoted back at them in a follow-up, and written into
 * their report.
 *
 * So this is a post-recognition correction pass over the terms this product
 * actually cares about: Java, Spring, and the CS fundamentals in the question
 * bank.
 *
 * WHAT IT DELIBERATELY DOES NOT DO. It does not guess. Every rule below is a
 * term where the correct form is unambiguous and the mis-heard form has no other
 * plausible meaning in an interview answer. "hash map" is always HashMap. "annual
 * function" — the artifact that caused a real bug — is NOT in here, because
 * nobody can know what was actually said, and inventing a correction would put
 * words in the candidate's mouth exactly as the old cross-question prompt did.
 *
 * Over-correcting is worse than under-correcting: a missed correction leaves the
 * transcript slightly wrong, a wrong correction makes it confidently wrong.
 *
 * ORDER MATTERS. Longer, more specific phrases run before their components, so
 * "null pointer exception" becomes NullPointerException rather than
 * "null pointer" + "exception" fighting each other.
 */

/** A correction: what the recogniser tends to produce → what was meant. */
interface Rule {
  /** Case-insensitive, word-boundary anchored. */
  pattern: RegExp;
  replacement: string;
}

/**
 * Build a word-boundary rule from a spoken form.
 *
 * `\b` on both sides so "a p i" never matches inside "rapid", and spaces become
 * `\s+` so "hash  map" and "hash map" both hit. Escaped because a few terms
 * contain characters that are regex-significant.
 */
function rule(spoken: string, meant: string): Rule {
  const escaped = spoken.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
  return { pattern: new RegExp(`\\b${escaped}\\b`, 'gi'), replacement: meant };
}

const RULES: Rule[] = [
  // ── Multi-word exceptions first, or their components would match instead ───
  rule('null pointer exception', 'NullPointerException'),
  rule('nullpointer exception', 'NullPointerException'),
  rule('class not found exception', 'ClassNotFoundException'),
  rule('index out of bounds', 'IndexOutOfBounds'),
  rule('array index out of bounds', 'ArrayIndexOutOfBounds'),
  rule('number format exception', 'NumberFormatException'),
  rule('illegal argument exception', 'IllegalArgumentException'),
  rule('sql exception', 'SQLException'),
  rule('i o exception', 'IOException'),
  rule('io exception', 'IOException'),
  rule('stack overflow error', 'StackOverflowError'),
  rule('out of memory error', 'OutOfMemoryError'),

  // ── Collections and core types ────────────────────────────────────────────
  rule('hash map', 'HashMap'),
  rule('hashmap', 'HashMap'),
  rule('hash set', 'HashSet'),
  rule('hash table', 'Hashtable'),
  rule('concurrent hash map', 'ConcurrentHashMap'),
  rule('array list', 'ArrayList'),
  rule('arraylist', 'ArrayList'),
  rule('linked list', 'LinkedList'),
  rule('linked hash map', 'LinkedHashMap'),
  rule('tree map', 'TreeMap'),
  rule('tree set', 'TreeSet'),
  rule('array deque', 'ArrayDeque'),
  rule('string builder', 'StringBuilder'),
  rule('stringbuilder', 'StringBuilder'),
  rule('string buffer', 'StringBuffer'),
  rule('stringbuffer', 'StringBuffer'),
  rule('buffered reader', 'BufferedReader'),
  rule('bufferedreader', 'BufferedReader'),
  rule('prepared statement', 'PreparedStatement'),
  rule('entity manager', 'EntityManager'),
  rule('object mapper', 'ObjectMapper'),
  rule('atomic integer', 'AtomicInteger'),
  rule('executor service', 'ExecutorService'),

  // ── Acronyms. The recogniser spells these out letter by letter. ────────────
  rule('j v m', 'JVM'),
  rule('jvm', 'JVM'),
  rule('j d k', 'JDK'),
  rule('jdk', 'JDK'),
  rule('j r e', 'JRE'),
  rule('jre', 'JRE'),
  rule('j d b c', 'JDBC'),
  rule('jdbc', 'JDBC'),
  rule('j p a', 'JPA'),
  rule('jpa', 'JPA'),
  rule('j s o n', 'JSON'),
  rule('json', 'JSON'),
  rule('a p i', 'API'),
  rule('api', 'API'),
  rule('rest a p i', 'REST API'),
  rule('http', 'HTTP'),
  rule('h t t p', 'HTTP'),
  rule('s q l', 'SQL'),
  rule('sql', 'SQL'),
  // "sequel" is how the recogniser writes SQL when it is spoken aloud, and it is
  // not a word that otherwise appears in a technical answer.
  rule('sequel', 'SQL'),
  rule('o o p', 'OOP'),
  rule('oops concept', 'OOP concept'),
  rule('oops concepts', 'OOP concepts'),
  rule('d b m s', 'DBMS'),
  rule('dbms', 'DBMS'),
  rule('c r u d', 'CRUD'),
  rule('u r l', 'URL'),
  rule('i d e', 'IDE'),
  rule('g c', 'GC'),
  rule('jit', 'JIT'),
  rule('j i t', 'JIT'),
  rule('orm', 'ORM'),
  rule('o r m', 'ORM'),
  rule('ioc', 'IoC'),
  rule('i o c', 'IoC'),
  rule('lifo', 'LIFO'),
  rule('fifo', 'FIFO'),

  // ── Split words the recogniser separates ──────────────────────────────────
  rule('poly morphism', 'polymorphism'),
  rule('in capsulation', 'encapsulation'),
  rule('en capsulation', 'encapsulation'),
  rule('over riding', 'overriding'),
  rule('over loading', 'overloading'),
  rule('multi threading', 'multithreading'),
  rule('multi thread', 'multithread'),
  rule('con currency', 'concurrency'),
  rule('data base', 'database'),
  rule('data bases', 'databases'),
  rule('micro services', 'microservices'),
  rule('micro service', 'microservice'),
  rule('gar bage collection', 'garbage collection'),
  rule('type casting', 'typecasting'),
  rule('auto boxing', 'autoboxing'),
  rule('un boxing', 'unboxing'),
  rule('run time', 'runtime'),
  rule('com pile time', 'compile time'),
  rule('byte code', 'bytecode'),
  rule('life cycle', 'lifecycle'),
  rule('call back', 'callback'),

  // ── Products and frameworks ───────────────────────────────────────────────
  rule('java script', 'JavaScript'),
  rule('javascript', 'JavaScript'),
  rule('type script', 'TypeScript'),
  rule('spring boot', 'Spring Boot'),
  rule('springboot', 'Spring Boot'),
  rule('hibernate', 'Hibernate'),
  rule('jackson', 'Jackson'),
  rule('maven', 'Maven'),
  rule('gradle', 'Gradle'),
  rule('junit', 'JUnit'),
  rule('j unit', 'JUnit'),
  rule('post gres', 'Postgres'),
  rule('postgres', 'Postgres'),
  rule('my sql', 'MySQL'),
  rule('mysql', 'MySQL'),
  rule('mongo db', 'MongoDB'),
  rule('react js', 'React'),
  rule('node js', 'Node.js'),
  rule('git hub', 'GitHub'),
  rule('rest controller', 'RestController'),
  rule('auto wired', 'Autowired'),
  rule('bean factory', 'BeanFactory'),
  rule('application context', 'ApplicationContext'),

  // ── Java keywords, which the recogniser lowercases inconsistently ─────────
  rule('final ise', 'finalize'),
  rule('finalise', 'finalize'),
];

/*
 * ── MISHEARINGS, WHICH NEED A GUARD ──────────────────────────────────────────
 *
 * Everything above is a term the recogniser SPLITS or spells out, where the wrong form is
 * not a word anyone would otherwise say. "hash map" is always HashMap.
 *
 * This section is different and more dangerous. The recogniser also SUBSTITUTES ordinary
 * English for technical words that sound like it — reported from a real session, and visible
 * in that transcript: "you keep the FEELS private and only allow access through public
 * CATCHERS". Both of those are real words. A blind `feels -> fields` rule would rewrite
 * "it feels wrong" in the middle of somebody's actual sentence, and a transcript that is
 * confidently wrong is worse than one that is obviously wrong: it gets scored, quoted back
 * in a follow-up, and printed in their report.
 *
 * So every rule here requires a TECHNICAL ANCHOR beside the mis-heard word. "feels" alone is
 * left exactly as it is; "private feels" is not something anyone says, so it is safe.
 *
 * No lookbehind. It is unsupported on Safari before 16.4, and a meaningful share of this
 * product's users are on older iPhones — a regex that throws at parse time would take the
 * whole correction pass down with it. Capture groups and $1 do the same job everywhere.
 */
const MISHEARD: Rule[] = [
  // fields — "keep the feels private", "instance feels"
  {
    pattern:
      /\b(private|public|protected|static|instance|member|class|these|those|the|its|all)\s+feels\b/gi,
    replacement: '$1 fields',
  },
  { pattern: /\bfeels\s+(are|is)\s+(private|public|protected|static)\b/gi, replacement: 'fields $1 $2' },

  // getters and setters — "public catchers", "gutters and setters"
  // Either half can be the one that was misheard, so the pair is matched with both sides
  // optional-but-anchored rather than assuming the first word is always the wrong one.
  { pattern: /\b(getters|catchers|gutters|guttars)\s+and\s+(setters|settlers|sitters)\b/gi, replacement: 'getters and setters' },
  { pattern: /\b(setters|settlers|sitters)\s+and\s+(getters|catchers|gutters)\b/gi, replacement: 'setters and getters' },
  { pattern: /\b(public|private|through|using|via|the)\s+(catchers|gutters)\b/gi, replacement: '$1 getters' },
  { pattern: /\b(public|private|through|using|via|the)\s+(settlers|sitters)\b/gi, replacement: '$1 setters' },

  // void — "public avoid main" is the classic
  { pattern: /\b(public|private|protected|static|returns?|return type)\s+avoid\b/gi, replacement: '$1 void' },
  { pattern: /\bavoid\s+main\b/gi, replacement: 'void main' },

  // null — "no pointer exception", "returns no"
  { pattern: /\bno\s+pointer\b/gi, replacement: 'null pointer' },
  { pattern: /\b(returns?|assign|assigned|checks? for|equals)\s+no\b/gi, replacement: '$1 null' },

  // thread — "threat safe", "threat pool"
  { pattern: /\bthreat\s+(safe|safety|pool|local|dump|priority)\b/gi, replacement: 'thread $1' },
  { pattern: /\b(multi|single|worker|main|new)\s+threat\b/gi, replacement: '$1 thread' },

  // cache — only near a memory or storage word, because "cash" is a real word
  { pattern: /\b(memory|cpu|browser|local|distributed|redis|l1|l2|write|read)\s+cash\b/gi, replacement: '$1 cache' },
  { pattern: /\bcash\s+(memory|hit|miss|line|eviction|invalidation)\b/gi, replacement: 'cache $1' },

  // byte — "bite code", "bite array"
  { pattern: /\bbite\s+(code|array|stream|size)\b/gi, replacement: 'byte $1' },
  { pattern: /\b(\d+)\s+bites\b/gi, replacement: '$1 bytes' },

  // wrapper — "rapper class"
  { pattern: /\brapper\s+(class|classes|type|types|object)\b/gi, replacement: 'wrapper $1' },

  // char — "car array", "car data type"
  { pattern: /\bcar\s+(array|data type|datatype|variable|literal)\b/gi, replacement: 'char $1' },

  // queue — "priority cue", "cue and stack"
  { pattern: /\b(priority|linked|blocking|circular|message)\s+cue\b/gi, replacement: '$1 queue' },
  { pattern: /\bcue\s+(data structure|and stack|is empty)\b/gi, replacement: 'queue $1' },

  // args — "string arcs"
  { pattern: /\b(string|command line)\s+arcs\b/gi, replacement: '$1 args' },

  // class — tightly guarded. "where clause" and "if clause" are real SQL and grammar terms,
  // so this only fires next to words that are unambiguously about OOP.
  { pattern: /\b(abstract|inner|outer|nested|anonymous|parent|child|base|derived|wrapper)\s+clause\b/gi, replacement: '$1 class' },

  // boolean — "bullion value"
  { pattern: /\bbullion\b/gi, replacement: 'boolean' },

  // interface — "inter face"
  { pattern: /\binter\s+face\b/gi, replacement: 'interface' },
  { pattern: /\bin\s+heritance\b/gi, replacement: 'inheritance' },
  { pattern: /\bin\s+stance\s+(variable|method|of)\b/gi, replacement: 'instance $1' },
  { pattern: /\bconstruct\s+or\b/gi, replacement: 'constructor' },
  { pattern: /\bsingle\s+ton\s+(pattern|class|design)\b/gi, replacement: 'singleton $1' },
  { pattern: /\bim\s+mutable\b/gi, replacement: 'immutable' },
  { pattern: /\ba\s+ray\s+(list|of|index|element)\b/gi, replacement: 'array $1' },
  { pattern: /\bprim\s+itive\b/gi, replacement: 'primitive' },
  { pattern: /\be\s+num\b/gi, replacement: 'enum' },
  { pattern: /\bit\s+rate\s+(over|through)\b/gi, replacement: 'iterate $1' },
];

/**
 * Apply the domain corrections to a transcript.
 *
 * Idempotent: running it twice changes nothing, because each replacement is
 * already in its corrected form and the patterns are case-insensitive. That
 * matters because the hook corrects each finalised chunk as it arrives and the
 * caller may correct the whole thing again before submitting.
 */
export function correctTechnicalTerms(text: string): string {
  if (!text) return text;
  let out = text;
  // Mishearings FIRST. They restore the technical word — "feels" becomes "fields",
  // "clause" becomes "class" — and several of the rules above then depend on that word
  // being present. Running them the other way round would leave every substitution
  // uncorrected, because RULES matches terms and MISHEARD matches the wrong words.
  for (const { pattern, replacement } of MISHEARD) {
    out = out.replace(pattern, replacement);
  }
  for (const { pattern, replacement } of RULES) {
    out = out.replace(pattern, replacement);
  }
  return out;
}

/**
 * Tidy the shape of a spoken transcript.
 *
 * The recogniser returns a run-on lowercase stream with no sentence structure:
 * "the jvm runs bytecode it is platform independent". That is hard to read back
 * in the detailed analysis and it makes an answer look worse than it was.
 *
 * Only safe, mechanical fixes — collapse whitespace, drop the space before
 * punctuation, capitalise sentence starts. No invented punctuation: guessing
 * where a sentence ended would change the meaning of what someone said.
 */
export function tidyTranscript(text: string): string {
  return text
    .replace(/\s+/g, ' ')
    .replace(/\s+([,.!?;:])/g, '$1')
    .replace(/([.!?])\s*([a-z])/g, (_m, p, c) => `${p} ${c.toUpperCase()}`)
    .replace(/^\s*([a-z])/, (_m, c) => c.toUpperCase())
    .trim();
}

/** Correct terminology, then tidy the shape. The order matters: corrections
 *  introduce capitals that the tidier must not undo. */
export function polishTranscript(text: string): string {
  return tidyTranscript(correctTechnicalTerms(text));
}
