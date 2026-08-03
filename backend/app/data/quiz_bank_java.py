"""
Java & Spring MCQ bank — app/data/quiz_bank_java.py

The same topics as `java_fundamentals.py`, but as multiple choice and spanning
easy → medium → hard. The split is deliberate: an interview is spoken, so it asks
theory at easy-to-medium; a quiz is read at your own pace with four options in
front of you, so it can afford the hard cases — the `Integer` cache, the
`finally`-overrides-`return` trap, `@Transactional` on a private method.

Every item carries an explicit `difficulty`. That field was already being read by
the quiz endpoint (`q.get("difficulty", "medium")`) but no question in the bank
had ever set it, so every question in the product reported itself as medium and
the easy/hard distinction did not exist.

Item shape, matching the rest of the bank:
    question, options[4], correct_index (0-3), explanation, difficulty
"""

from __future__ import annotations

JAVA_QUIZ_BANK: dict[str, list[dict]] = {
    # ── The platform ──────────────────────────────────────────────────────────
    "JVM, JDK & Java I/O": [
        {
            "question": "Which of these contains the other two?",
            "options": ["JVM", "JRE", "JDK", "They are unrelated"],
            "correct_index": 2,
            "explanation": "JDK ⊃ JRE ⊃ JVM. The JDK adds development tools (javac, javadoc, debugger) to the JRE, and the JRE adds the standard libraries to the JVM.",
            "difficulty": "easy",
        },
        {
            "question": "What does javac produce?",
            "options": [
                "Native machine code for the current CPU",
                "Platform-independent bytecode in a .class file",
                "An executable .exe",
                "Optimised assembly",
            ],
            "correct_index": 1,
            "explanation": "javac compiles source to bytecode, not machine code. The JVM then interprets that bytecode — and JIT-compiles the hot paths to native code at runtime. This two-step is what makes the same .class file run anywhere.",
            "difficulty": "easy",
        },
        {
            "question": "Where are local primitive variables stored?",
            "options": ["Heap", "Stack", "Metaspace", "String pool"],
            "correct_index": 1,
            "explanation": "The stack holds method frames: local primitives and references. The objects those references point at live on the heap. Each thread has its own stack; the heap is shared.",
            "difficulty": "easy",
        },
        {
            "question": "A deeply recursive method with no base case throws which error?",
            "options": ["OutOfMemoryError", "StackOverflowError", "IllegalStateException", "RuntimeException"],
            "correct_index": 1,
            "explanation": "Each call pushes a frame onto the thread's stack; exhausting it throws StackOverflowError. OutOfMemoryError is the heap equivalent — too many live objects.",
            "difficulty": "easy",
        },
        {
            "question": "Which is faster for reading large amounts of input, and why?",
            "options": [
                "Scanner, because it parses as it reads",
                "BufferedReader, because it has a larger buffer and does no parsing",
                "They are identical",
                "Scanner, because it is synchronized",
            ],
            "correct_index": 1,
            "explanation": "BufferedReader reads into a large buffer and hands back raw lines, so you parse yourself with Integer.parseInt. Scanner does regex-based tokenising on every call, which is convenient but much slower — which is why competitive programmers use BufferedReader.",
            "difficulty": "easy",
        },
        {
            "question": "Which of these does Scanner give you that BufferedReader does not?",
            "options": [
                "Thread safety",
                "Typed reads like nextInt() and nextDouble()",
                "A larger internal buffer",
                "Non-blocking reads",
            ],
            "correct_index": 1,
            "explanation": "Scanner parses as it reads, so nextInt() returns an int directly and you can split on a custom delimiter. BufferedReader only returns Strings — but it is the synchronized one, and the faster one.",
            "difficulty": "medium",
        },
        {
            "question": "Since Java 8, where is class metadata stored?",
            "options": ["PermGen", "Metaspace", "The heap's young generation", "The stack"],
            "correct_index": 1,
            "explanation": "PermGen was removed in Java 8 and replaced by Metaspace, which lives in native memory and grows automatically — which is why PermGen OutOfMemoryErrors stopped being a common problem.",
            "difficulty": "hard",
        },
    ],
    # ── Strings ───────────────────────────────────────────────────────────────
    "Strings & String Pool": [
        {
            "question": "What does `\"abc\" == \"abc\"` evaluate to in Java?",
            "options": ["true", "false", "It does not compile", "Depends on the JVM"],
            "correct_index": 0,
            "explanation": "Both literals are interned in the String pool, so they are the same object and == is true. With `new String(\"abc\")` it would be false — same content, different object.",
            "difficulty": "easy",
        },
        {
            "question": "Which comparison should you use to check whether two Strings have the same characters?",
            "options": ["==", ".equals()", "compareTo() == 1", "hashCode() =="],
            "correct_index": 1,
            "explanation": ".equals() compares content. == compares references. Equal hashCodes do not guarantee equality — different strings can collide.",
            "difficulty": "easy",
        },
        {
            "question": "How many String objects does `String s = new String(\"hi\");` create at most?",
            "options": ["1", "2", "0", "3"],
            "correct_index": 1,
            "explanation": "Up to two: the literal \"hi\" goes in the pool (if not already there), and `new` creates a separate heap object. This is why `new String(literal)` is considered wasteful.",
            "difficulty": "medium",
        },
        {
            "question": "Which is thread-safe?",
            "options": ["StringBuilder", "StringBuffer", "Both", "Neither"],
            "correct_index": 1,
            "explanation": "StringBuffer's methods are synchronized, StringBuilder's are not. StringBuilder is faster and is the right default in single-threaded code, which is almost all code.",
            "difficulty": "easy",
        },
        {
            "question": "Concatenating strings with + inside a loop of n iterations costs roughly:",
            "options": ["O(1)", "O(n)", "O(n²)", "O(log n)"],
            "correct_index": 2,
            "explanation": "Strings are immutable, so each + allocates a new string and copies everything so far — quadratic in total. A StringBuilder appends into one buffer and is O(n).",
            "difficulty": "medium",
        },
        {
            "question": "Why can Strings be safely shared in the String pool?",
            "options": [
                "They are synchronized",
                "They are immutable, so no reference can change the value",
                "The pool copies them defensively on read",
                "The garbage collector locks them",
            ],
            "correct_index": 1,
            "explanation": "Immutability is the precondition for sharing. If one holder could mutate the value, every other holder of that pooled object would see the change. It also makes Strings safe HashMap keys and lets the hash be cached.",
            "difficulty": "hard",
        },
    ],
    # ── OOP ───────────────────────────────────────────────────────────────────
    "OOP & Class Design": [
        {
            "question": "Can a static method access an instance variable directly?",
            "options": ["Yes", "No, there is no `this` to resolve it against", "Only if the variable is final", "Only inside a constructor"],
            "correct_index": 1,
            "explanation": "A static method belongs to the class, so there is no particular instance and no `this`. It can only touch static members or something passed in as a parameter.",
            "difficulty": "easy",
        },
        {
            "question": "Making a field private and adding a getter but no setter gives you:",
            "options": ["A write-only field", "A read-only field from outside the class", "A static field", "No change in behaviour"],
            "correct_index": 1,
            "explanation": "Outside code can read it and cannot assign it — the standard way to expose immutable state. That control is the point of encapsulation; a public field gives it up permanently.",
            "difficulty": "easy",
        },
        {
            "question": "How does Java prevent the diamond problem for classes?",
            "options": [
                "It resolves left to right",
                "A class may extend only one class",
                "It throws at runtime",
                "It merges the two methods",
            ],
            "correct_index": 1,
            "explanation": "Single class inheritance removes the ambiguity entirely. It resurfaced with Java 8 default methods, and there the compiler forces you to override the clash explicitly.",
            "difficulty": "medium",
        },
        {
            "question": "A class implements two interfaces that both declare the same default method. What happens?",
            "options": [
                "The first interface listed wins",
                "It runs but the behaviour is undefined",
                "Compile error until the class overrides the method",
                "Both run in order",
            ],
            "correct_index": 2,
            "explanation": "Java refuses to guess. You must override it, and you can delegate to one explicitly with `InterfaceName.super.method()`.",
            "difficulty": "hard",
        },
        {
            "question": "What does `Integer a = 127, b = 127; a == b;` evaluate to?",
            "options": ["true", "false", "Compile error", "Depends on the platform"],
            "correct_index": 0,
            "explanation": "Integer caches −128..127, so both autobox to the same cached object. At 128 the same code returns false — which is exactly why you compare wrappers with .equals(), never ==.",
            "difficulty": "hard",
        },
        {
            "question": "Unboxing a null Integer into an int throws:",
            "options": ["NumberFormatException", "NullPointerException", "IllegalArgumentException", "Nothing — it becomes 0"],
            "correct_index": 1,
            "explanation": "Unboxing calls intValue() on the wrapper, so a null reference throws NullPointerException. A common surprise when a database column or Map lookup returns null.",
            "difficulty": "medium",
        },
    ],
    # ── Collections ───────────────────────────────────────────────────────────
    "Collections Framework": [
        {
            "question": "Which collection does NOT allow duplicate elements?",
            "options": ["List", "Set", "Queue", "ArrayList"],
            "correct_index": 1,
            "explanation": "Set rejects duplicates, using equals/hashCode to decide. Lists and Queues allow them.",
            "difficulty": "easy",
        },
        {
            "question": "Getting element at index n from an ArrayList is:",
            "options": ["O(1)", "O(log n)", "O(n)", "O(n log n)"],
            "correct_index": 0,
            "explanation": "ArrayList is array-backed, so indexed access is constant time. LinkedList's get(n) is O(n) because it walks the nodes.",
            "difficulty": "easy",
        },
        {
            "question": "You override equals() but not hashCode(). What breaks?",
            "options": [
                "Nothing",
                "Lookups in HashMap and HashSet stop finding equal objects",
                "The class will not compile",
                "toString() returns null",
            ],
            "correct_index": 1,
            "explanation": "Equal objects can then produce different hash codes, so a lookup goes to the wrong bucket and misses. The contract is: equal objects MUST have equal hash codes.",
            "difficulty": "medium",
        },
        {
            "question": "Since Java 8, a HashMap bucket with many colliding keys converts to:",
            "options": ["A second array", "A balanced tree", "A linked list", "A skip list"],
            "correct_index": 1,
            "explanation": "Past a threshold (about 8) the chain becomes a red-black tree, improving worst-case lookup from O(n) to O(log n) — a hardening measure against hash-collision attacks.",
            "difficulty": "hard",
        },
        {
            "question": "Which does NOT permit null keys?",
            "options": ["HashMap", "ConcurrentHashMap", "LinkedHashMap", "TreeMap with a null-safe comparator"],
            "correct_index": 1,
            "explanation": "ConcurrentHashMap forbids null keys and values — with concurrent access, a null return would be ambiguous between 'absent' and 'present but null'. HashMap allows one null key.",
            "difficulty": "hard",
        },
        {
            "question": "Removing from the middle of an ArrayList of size n costs:",
            "options": ["O(1)", "O(n) because later elements shift", "O(log n)", "O(n²)"],
            "correct_index": 1,
            "explanation": "Everything after the removed index moves down one slot. LinkedList removal at a known node is O(1), but finding that node is O(n).",
            "difficulty": "medium",
        },
    ],
    # ── Exceptions ────────────────────────────────────────────────────────────
    "Exception Handling": [
        {
            "question": "Which is a checked exception?",
            "options": ["NullPointerException", "IOException", "ArithmeticException", "ArrayIndexOutOfBoundsException"],
            "correct_index": 1,
            "explanation": "IOException extends Exception but not RuntimeException, so the compiler forces you to catch or declare it. The other three are unchecked.",
            "difficulty": "easy",
        },
        {
            "question": "`throws` appears where?",
            "options": ["Inside a method body", "In the method signature", "Inside a catch block", "Before a class name"],
            "correct_index": 1,
            "explanation": "`throws` declares what a method might raise, in its signature. `throw` is the statement inside the body that actually raises one.",
            "difficulty": "easy",
        },
        {
            "question": "Which of final, finally and finalize is deprecated?",
            "options": ["final", "finally", "finalize", "None"],
            "correct_index": 2,
            "explanation": "finalize() was the GC callback and was unreliable about when — or whether — it ran. Deprecated since Java 9; use try-with-resources or Cleaner instead.",
            "difficulty": "easy",
        },
        {
            "question": "A `finally` block contains a `return`. The `try` block also returns. Which value is returned?",
            "options": ["The try's value", "The finally's value", "Both, in order", "Compile error"],
            "correct_index": 1,
            "explanation": "finally runs after the try's return value is computed but before it is handed back, and its own return overrides it — silently discarding the try's value, and any in-flight exception. Which is why returning from finally is a bug, not a technique.",
            "difficulty": "hard",
        },
        {
            "question": "When is a `finally` block skipped?",
            "options": [
                "Never",
                "When the try block returns",
                "When System.exit() is called or the JVM dies",
                "When an exception is thrown",
            ],
            "correct_index": 2,
            "explanation": "finally runs on normal completion, on return, and on exception. Only killing the JVM — System.exit(), a crash, or the thread being destroyed — skips it.",
            "difficulty": "medium",
        },
    ],
    # ── Threads ───────────────────────────────────────────────────────────────
    "Multithreading": [
        {
            "question": "Which starts a new thread of execution?",
            "options": ["thread.run()", "thread.start()", "thread.execute()", "new Thread()"],
            "correct_index": 1,
            "explanation": "start() asks the JVM for a new thread which then calls run(). Calling run() directly just executes it on the current thread — a very common interview trap.",
            "difficulty": "easy",
        },
        {
            "question": "Why is implementing Runnable usually preferred to extending Thread?",
            "options": [
                "Runnable is faster",
                "Java allows only one superclass, so extending Thread spends it",
                "Thread is deprecated",
                "Runnable is thread-safe",
            ],
            "correct_index": 1,
            "explanation": "Extending Thread uses up your single inheritance slot and couples the task to the mechanism running it. Runnable separates the two and can be handed to an ExecutorService.",
            "difficulty": "easy",
        },
        {
            "question": "Why is `count++` unsafe across threads?",
            "options": [
                "It is atomic but slow",
                "It is read-modify-write, so two threads can lose an increment",
                "It throws ConcurrentModificationException",
                "It is safe",
            ],
            "correct_index": 1,
            "explanation": "It compiles to three operations. Two threads can read the same value, both add one, and both write back — one increment vanishes. AtomicInteger or synchronized fixes it.",
            "difficulty": "medium",
        },
        {
            "question": "`volatile` guarantees:",
            "options": [
                "Atomicity of compound operations",
                "Visibility of writes across threads, but not atomicity",
                "Mutual exclusion",
                "Both atomicity and mutual exclusion",
            ],
            "correct_index": 1,
            "explanation": "volatile makes a write visible to other threads immediately and prevents reordering, but count++ on a volatile is still not atomic. Visibility and atomicity are separate problems.",
            "difficulty": "hard",
        },
        {
            "question": "Two threads each hold a lock the other needs. This is:",
            "options": ["Starvation", "Deadlock", "A race condition", "Livelock"],
            "correct_index": 1,
            "explanation": "Deadlock — neither can proceed. Acquiring locks in a consistent global order is the usual prevention.",
            "difficulty": "medium",
        },
    ],
    # ── Java 8 ────────────────────────────────────────────────────────────────
    "Java 8 & Lambdas": [
        {
            "question": "A functional interface has exactly how many abstract methods?",
            "options": ["Zero", "One", "Two", "Any number"],
            "correct_index": 1,
            "explanation": "Exactly one — that is what lets the compiler infer what a lambda means. It may also have any number of default and static methods. @FunctionalInterface enforces the rule.",
            "difficulty": "easy",
        },
        {
            "question": "Which is a terminal Stream operation?",
            "options": ["filter()", "map()", "collect()", "sorted()"],
            "correct_index": 2,
            "explanation": "collect() triggers the pipeline and produces a result. filter, map and sorted are intermediate — lazy, and they just build the pipeline up.",
            "difficulty": "easy",
        },
        {
            "question": "What happens if you call a terminal operation on a stream twice?",
            "options": [
                "It runs again",
                "IllegalStateException — a stream cannot be reused",
                "It returns a cached result",
                "It returns an empty result",
            ],
            "correct_index": 1,
            "explanation": "A stream is consumed by its terminal operation. Reuse throws IllegalStateException; you need a fresh stream from the source.",
            "difficulty": "medium",
        },
        {
            "question": "Given a list of 1,000,000 items, `list.stream().filter(...).findFirst()` evaluates:",
            "options": [
                "All items, then takes the first",
                "Only as many as needed to find one match",
                "The first 1,000",
                "Nothing until collect() is called",
            ],
            "correct_index": 1,
            "explanation": "Streams are lazy and findFirst short-circuits, so elements flow through one at a time and evaluation stops at the first match. That laziness is the main performance argument for streams.",
            "difficulty": "hard",
        },
        {
            "question": "Which functional interface takes a value and returns a boolean?",
            "options": ["Function", "Consumer", "Predicate", "Supplier"],
            "correct_index": 2,
            "explanation": "Predicate<T> is T → boolean, used by filter(). Function<T,R> transforms, Consumer<T> takes and returns nothing, Supplier<T> returns without taking.",
            "difficulty": "easy",
        },
    ],
    # ── Data access ───────────────────────────────────────────────────────────
    "JDBC, Hibernate & JPA": [
        {
            "question": "Which prevents SQL injection?",
            "options": ["Statement with concatenated input", "PreparedStatement with ? placeholders", "Escaping quotes by hand", "Using a Connection pool"],
            "correct_index": 1,
            "explanation": "PreparedStatement sends the query and the values separately, so input is always data and never parsed as SQL. Hand-escaping is fragile and gets it wrong.",
            "difficulty": "easy",
        },
        {
            "question": "JPA is:",
            "options": [
                "An ORM implementation",
                "A specification that Hibernate implements",
                "A database driver",
                "A Spring module",
            ],
            "correct_index": 1,
            "explanation": "JPA is the spec — annotations and the EntityManager API. Hibernate is the usual implementation. Coding against JPA keeps you portable between providers.",
            "difficulty": "medium",
        },
        {
            "question": "The main advantage of Hibernate over raw JDBC is:",
            "options": [
                "It is always faster",
                "It maps objects to tables, removing most boilerplate",
                "It does not need a driver",
                "It avoids SQL entirely in all cases",
            ],
            "correct_index": 1,
            "explanation": "It is an ORM: entity annotations replace hand-written mapping code. It is not automatically faster — the N+1 select problem is a classic Hibernate performance trap.",
            "difficulty": "medium",
        },
        {
            "question": "Loading a parent entity, then its children one query at a time inside a loop, is known as:",
            "options": ["Eager loading", "The N+1 select problem", "Second-level caching", "Dirty checking"],
            "correct_index": 1,
            "explanation": "One query for the parents plus N for the children. Fixed with a join fetch or an @EntityGraph — the single most common Hibernate performance bug.",
            "difficulty": "hard",
        },
        {
            "question": "Which JDBC step is easiest to get wrong and leaks resources?",
            "options": ["Loading the driver", "Closing Connection/Statement/ResultSet", "Building the URL", "Reading the ResultSet"],
            "correct_index": 1,
            "explanation": "An exception between open and close leaks the connection until the pool is exhausted. try-with-resources closes them in reverse order automatically.",
            "difficulty": "medium",
        },
    ],
    # ── Spring ────────────────────────────────────────────────────────────────
    "Spring Boot & REST": [
        {
            "question": "Which annotation makes a class return data as the HTTP response body?",
            "options": ["@Controller", "@RestController", "@Service", "@Component"],
            "correct_index": 1,
            "explanation": "@RestController is @Controller + @ResponseBody, so returned objects are serialised to the body instead of being resolved as a view name.",
            "difficulty": "easy",
        },
        {
            "question": "Which HTTP methods are idempotent?",
            "options": ["POST only", "GET, PUT and DELETE", "GET and POST", "None"],
            "correct_index": 1,
            "explanation": "Repeating them leaves the same end state. POST is not idempotent — sending it twice creates two resources, which is why retrying a POST needs care.",
            "difficulty": "medium",
        },
        {
            "question": "Constructor injection is preferred over field @Autowired mainly because:",
            "options": [
                "It is faster at startup",
                "Dependencies are explicit and the object is never half-built",
                "It allows circular dependencies",
                "It skips the IoC container",
            ],
            "correct_index": 1,
            "explanation": "A required dependency in the constructor cannot be forgotten, the field can be final, and the class is testable with plain `new`. Field injection hides dependencies and needs reflection to set in a test.",
            "difficulty": "medium",
        },
        {
            "question": "Which annotation keeps a field out of the JSON Jackson produces?",
            "options": ["@JsonProperty", "@JsonIgnore", "@Transient", "@JsonInclude"],
            "correct_index": 1,
            "explanation": "@JsonIgnore excludes it from serialisation — the standard way to keep a password hash out of an API response. @Transient is JPA and controls persistence, not JSON.",
            "difficulty": "medium",
        },
        {
            "question": "Which status code means the request was understood but the caller is not authenticated?",
            "options": ["400", "401", "403", "404"],
            "correct_index": 1,
            "explanation": "401 Unauthorized means 'who are you' — authentication is missing or invalid. 403 Forbidden means 'I know who you are and you still may not'.",
            "difficulty": "easy",
        },
        {
            "question": "@Transactional on a private method does what?",
            "options": [
                "Works as normal",
                "Nothing — Spring's proxy cannot intercept it",
                "Throws at startup",
                "Applies to the whole class",
            ],
            "correct_index": 1,
            "explanation": "Spring wraps the bean in a proxy that intercepts external calls to public methods. A private method, or one called from inside the same class, bypasses the proxy entirely — so the transaction silently never starts.",
            "difficulty": "hard",
        },
    ],
    # ── Design principles and patterns ────────────────────────────────────────
    "SOLID & Design Patterns": [
        {
            "question": "What does the S in SOLID stand for?",
            "options": [
                "Static responsibility",
                "Single responsibility",
                "Separation of interfaces",
                "Stateless resources",
            ],
            "correct_index": 1,
            "explanation": "Single Responsibility: a class should have one reason to change. The practical test is whether you can describe what it does in one sentence without saying \"and\".",
            "difficulty": "easy",
        },
        {
            "question": "\"Open for extension, closed for modification\" describes which principle?",
            "options": ["Liskov substitution", "Open-closed", "Interface segregation", "Dependency inversion"],
            "correct_index": 1,
            "explanation": "Open-closed: you add behaviour by adding a class, not by editing one that already works. The strategy pattern is this principle in practice.",
            "difficulty": "easy",
        },
        {
            "question": "A subclass that throws on a method its parent implements fine violates which principle?",
            "options": [
                "Single responsibility",
                "Liskov substitution",
                "Interface segregation",
                "Open-closed",
            ],
            "correct_index": 1,
            "explanation": "Liskov substitution: a subclass must work anywhere its parent does. The classic violation is Square extending Rectangle, where setWidth breaks the caller's assumption about height.",
            "difficulty": "hard",
        },
        {
            "question": "Spring's dependency injection is a direct application of which SOLID principle?",
            "options": ["Single responsibility", "Open-closed", "Dependency inversion", "Liskov substitution"],
            "correct_index": 2,
            "explanation": "Dependency inversion: depend on an abstraction, not a concrete class. Taking a UserRepository interface in the constructor rather than doing `new MySqlUserRepository()` is exactly this.",
            "difficulty": "medium",
        },
        {
            "question": "Which is the safest and simplest way to write a singleton in Java?",
            "options": [
                "A static field initialised lazily without locking",
                "A single-element enum",
                "double-checked locking without volatile",
                "A synchronized getInstance() called on every access",
            ],
            "correct_index": 1,
            "explanation": "An enum's single instance is guaranteed by the JVM and is serialisation-safe for free. Lazy init without locking is not thread-safe; double-checked locking needs volatile to be correct; a synchronized getter works but locks on every read.",
            "difficulty": "hard",
        },
        {
            "question": "What is the difference between the factory and builder patterns?",
            "options": [
                "Factory is thread-safe, builder is not",
                "Factory decides WHICH class to create; builder decides HOW to construct one",
                "They are the same pattern under two names",
                "Builder only works for immutable objects",
            ],
            "correct_index": 1,
            "explanation": "Factory hides the concrete type from the caller. Builder hides the assembly of one type that has many optional fields — StringBuilder and Stream.collect are both builders.",
            "difficulty": "medium",
        },
        {
            "question": "Swapping a sorting or pricing algorithm at runtime behind one interface is which pattern?",
            "options": ["Observer", "Strategy", "Adapter", "Decorator"],
            "correct_index": 1,
            "explanation": "Strategy: each algorithm is a class implementing a shared interface, chosen at runtime. It is also how you satisfy open-closed — a new rule is a new class, not an edit.",
            "difficulty": "medium",
        },
    ],
}
