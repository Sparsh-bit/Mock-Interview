"""
The Java interview question bank — app/data/java_fundamentals.py

The topics that actually get asked in Indian campus placements, written out in
full rather than left to the model to invent. Every one of these came off a list
of what Cognizant GenC Next, TCS, Infosys and Wipro really ask a fresher.

WHY THIS FILE EXISTS AT ALL. There were two seed banks before it, both with five
questions, and they had drifted apart: `knowledge/questions/java_core.yaml`, read
only by a manual seed script, and a hardcoded list inside
`orchestrator._ensure_seed_questions` used at runtime. Five questions cannot fill
a twelve-question interview, let alone twenty — so when the model returned a short
plan there was nothing to top it up from, and the candidate got whatever arrived.
This is now the single source both read.

TWO TIERS, because not every company asks everything.

  CORE       Asked in essentially every fresher interview, at every company on
             the catalogue. JVM, strings, collections, exceptions, OOP, threads.
  FRAMEWORK  Asked for Java backend and full-stack roles — Cognizant GenC Next
             Java FSE, Infosys Power Programmer, product companies. Spring Boot,
             JPA, Hibernate, Jackson, dependency injection.

The tier matters: putting a Spring dependency-injection question into a TCS NQT
round, which is aptitude-first and does not go near a framework, wastes one of
twelve slots on something the candidate will never be asked. `for_track()`
applies that rule.

DIFFICULTY. Interview questions here are `easy` and `medium` only, and
theoretical. A spoken interview is not the place for a hard multi-part design
question — the candidate has sixty seconds and no editor — and the quiz is where
`hard` belongs. See `app/data/quiz_bank.py`.

Each entry mirrors the Question model so seeding is a direct mapping:
  topic       groups it in the plan and the report's topic breakdown
  content     the question, as an interviewer would say it out loud
  difficulty  "easy" | "medium"
  type        "conceptual" | "practical"
  keywords    what a good answer mentions; drives scoring and gap detection
  ideal       a model answer at the length a candidate should actually speak
"""

from __future__ import annotations

from typing import Literal, TypedDict


class BankQuestion(TypedDict):
    topic: str
    content: str
    difficulty: Literal["easy", "medium"]
    type: Literal["conceptual", "practical"]
    keywords: list[str]
    ideal: str
    tier: Literal["core", "framework"]


# ─── Core Java: the platform ──────────────────────────────────────────────────

_PLATFORM: list[BankQuestion] = [
    {
        "topic": "JVM, JDK & JRE",
        "content": "What is the difference between the JDK, the JRE and the JVM?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["JDK", "JRE", "JVM", "compiler", "javac", "runtime", "development kit"],
        "ideal": (
            "The JVM is the engine that actually runs Java bytecode — it is what makes Java "
            "platform independent, because there is a different JVM for each operating system. "
            "The JRE is the JVM plus the standard libraries, so it is what you need to run a "
            "Java program. The JDK is the JRE plus the development tools like javac and the "
            "debugger, so it is what you need to write and compile one. So JDK contains JRE, "
            "and JRE contains JVM."
        ),
        "tier": "core",
    },
    {
        "topic": "JVM, JDK & JRE",
        "content": "Walk me through what happens from the moment you write a .java file to the moment it runs.",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["javac", "bytecode", ".class", "class loader", "JVM", "JIT", "interpreter"],
        "ideal": (
            "I write the source in a .java file. javac compiles it to bytecode in a .class file — "
            "that is not machine code, it is an intermediate format the JVM understands. When I run "
            "it, the class loader loads that .class into memory, the bytecode is verified for "
            "safety, and then the JVM executes it. The JVM interprets the bytecode, and the JIT "
            "compiler converts the hot paths to native machine code so it runs faster over time. "
            "That two-step compile-then-interpret is why the same .class file runs on Windows and "
            "Linux without recompiling."
        ),
        "tier": "core",
    },
    {
        "topic": "Memory: stack & heap",
        "content": "What is the difference between stack memory and heap memory in Java?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["stack", "heap", "method frame", "local variables", "objects", "garbage collection", "thread"],
        "ideal": (
            "The stack holds method call frames — local variables, primitives, and references to "
            "objects. Each thread gets its own stack, and memory is reclaimed automatically when "
            "the method returns, so it is fast and last-in-first-out. The heap is where the actual "
            "objects live, it is shared across all threads, and it is managed by the garbage "
            "collector. So if I write `String s = new String(\"hi\")`, the reference s is on the "
            "stack and the String object is on the heap. Too much recursion overflows the stack; "
            "too many live objects fills the heap."
        ),
        "tier": "core",
    },
]

# ─── Core Java: strings ───────────────────────────────────────────────────────

_STRINGS: list[BankQuestion] = [
    {
        "topic": "Strings & the String pool",
        "content": "What is the difference between == and .equals() in Java?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["reference comparison", "value comparison", "String pool", "override equals", "hashCode"],
        "ideal": (
            "== compares references — whether two variables point at the same object in memory. "
            "For primitives it compares the actual values. .equals() compares content, so for "
            "Strings it checks the characters. The catch is that string literals are interned in "
            "the String pool, so two identical literals are the same object and == happens to "
            "return true — but if I use new String(), == is false while .equals() is still true. "
            "For my own classes, .equals() defaults to == until I override it."
        ),
        "tier": "core",
    },
    {
        "topic": "Strings & the String pool",
        "content": "What is the String pool, and what is the difference between String s = \"abc\" and String s = new String(\"abc\")?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["String pool", "string literal", "interning", "heap", "immutable", "intern()"],
        "ideal": (
            "The String pool is a special area where the JVM keeps one copy of each string "
            "literal, so identical literals are reused instead of duplicated. `String s = \"abc\"` "
            "checks the pool first and reuses the existing object if it is there. "
            "`new String(\"abc\")` always creates a fresh object on the heap, outside the pool, "
            "even though the content is identical — so it wastes memory and breaks == comparisons. "
            "This works because Strings are immutable; sharing is only safe when nothing can change "
            "the value underneath you. You can put a heap string into the pool with .intern()."
        ),
        "tier": "core",
    },
    {
        "topic": "Strings & the String pool",
        "content": "Why is String immutable in Java, and what problem would it cause if it were not?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["immutable", "String pool", "thread safety", "hashCode caching", "security", "HashMap key"],
        "ideal": (
            "Immutability is what makes the String pool safe — if one reference could change the "
            "value, every other reference sharing that object would change too. It also makes "
            "Strings thread-safe with no synchronisation, lets the hash code be computed once and "
            "cached, and makes them reliable HashMap keys, because a key whose hash changes after "
            "insertion becomes unreachable. There is a security angle too: file paths and "
            "connection strings passed as Strings cannot be modified after a security check has "
            "validated them."
        ),
        "tier": "core",
    },
    {
        "topic": "Strings & the String pool",
        "content": "What is the difference between StringBuilder and StringBuffer, and when would you use either over String?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["mutable", "synchronized", "thread safe", "performance", "concatenation", "loop"],
        "ideal": (
            "Both are mutable, so appending changes the object instead of creating a new one. The "
            "difference is that StringBuffer's methods are synchronized and StringBuilder's are "
            "not, so StringBuffer is thread-safe but slower, and StringBuilder is the one you want "
            "in single-threaded code — which is almost always. I would use either over String when "
            "concatenating in a loop: String + in a loop creates a new object every iteration, "
            "which is O(n squared) on memory, whereas StringBuilder appends into one buffer."
        ),
        "tier": "core",
    },
]

# ─── Core Java: OOP and class design ──────────────────────────────────────────

_OOP: list[BankQuestion] = [
    {
        "topic": "OOP & class design",
        "content": "What does the static keyword mean, and can a static method access instance variables?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["class level", "instance", "no object required", "this", "main method", "shared"],
        "ideal": (
            "static means the member belongs to the class rather than to any one object, so there "
            "is one copy shared by every instance and you can call it without creating an object — "
            "which is why main is static. A static method cannot access instance variables or "
            "instance methods directly, because there is no `this`: it does not know which object "
            "you would mean. It can only touch other static members, or something you pass in as a "
            "parameter."
        ),
        "tier": "core",
    },
    {
        "topic": "OOP & class design",
        "content": "Why do we make fields private and expose getters and setters instead of making the fields public?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["encapsulation", "private", "validation", "read only", "control", "refactor"],
        "ideal": (
            "It is encapsulation. Making the field private means nothing outside the class can put "
            "it into an invalid state, and the setter gives me one place to validate — I can reject "
            "a negative age instead of letting anyone assign it. It also means I can change how the "
            "value is stored later without breaking every caller, and I can make a field read-only "
            "by providing a getter and no setter. A public field gives up all of that permanently, "
            "because callers depend on the field directly."
        ),
        "tier": "core",
    },
    {
        "topic": "OOP & class design",
        "content": "What is the diamond problem, and how does Java deal with it?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["multiple inheritance", "ambiguity", "interface", "default method", "super", "single inheritance"],
        "ideal": (
            "The diamond problem is the ambiguity you get with multiple inheritance: if B and C "
            "both extend A and override the same method, and D extends both B and C, the compiler "
            "cannot tell which version D should inherit. Java avoids it for classes by simply not "
            "allowing multiple class inheritance — a class extends exactly one class. It came back "
            "in Java 8 with default methods in interfaces, because a class can implement two "
            "interfaces that both have the same default method. Java handles that by refusing to "
            "compile until you override the method explicitly, and you can pick one with "
            "InterfaceName.super.method()."
        ),
        "tier": "core",
    },
    {
        "topic": "OOP & class design",
        "content": "What are wrapper classes, and what is autoboxing?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["Integer", "primitive", "object", "autoboxing", "unboxing", "collections", "null"],
        "ideal": (
            "Wrapper classes wrap a primitive in an object — Integer for int, Double for double, and "
            "so on. You need them because collections and generics only hold objects, so you cannot "
            "put an int in a List. Autoboxing is the compiler converting a primitive to its wrapper "
            "automatically, and unboxing is the reverse, so `list.add(5)` just works. Two things to "
            "watch: a wrapper can be null, so unboxing a null throws a NullPointerException, and "
            "Integer caches values from -128 to 127, so == comparisons on wrappers work by accident "
            "for small numbers and fail for large ones."
        ),
        "tier": "core",
    },
]

# ─── Core Java: collections ───────────────────────────────────────────────────

_COLLECTIONS: list[BankQuestion] = [
    {
        "topic": "Collections framework",
        "content": "Give me an overview of the Java Collections framework — the main interfaces and when you would use each.",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["List", "Set", "Map", "Queue", "ArrayList", "HashMap", "duplicates", "ordering"],
        "ideal": (
            "The three I use most are List, Set and Map. List is an ordered collection that allows "
            "duplicates, and ArrayList is the default because indexed access is O(1). Set does not "
            "allow duplicates — HashSet for speed, TreeSet when I need sorted order. Map holds "
            "key-value pairs, and HashMap is the workhorse. Queue is for FIFO processing. Under "
            "Collection there is also LinkedList, which is better when I am inserting and removing "
            "in the middle, since ArrayList has to shift elements."
        ),
        "tier": "core",
    },
    {
        "topic": "Collections framework",
        "content": "What is the difference between ArrayList and LinkedList, and which would you pick?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["dynamic array", "doubly linked list", "random access", "insertion", "O(1)", "O(n)", "memory"],
        "ideal": (
            "ArrayList is backed by a resizable array, so get by index is O(1), but inserting or "
            "removing in the middle is O(n) because everything after it shifts, and growing means "
            "allocating a bigger array and copying. LinkedList is a doubly linked list, so "
            "inserting or removing at a known position is O(1), but getting element n means walking "
            "n nodes. In practice I pick ArrayList almost always — reads dominate, and it has much "
            "better cache locality. LinkedList only wins when I am doing a lot of add and remove at "
            "the ends, and even then ArrayDeque is usually better."
        ),
        "tier": "core",
    },
    {
        "topic": "Collections framework",
        "content": "How does a HashMap work internally, and what happens when two keys have the same hash?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["hashCode", "bucket", "collision", "linked list", "tree", "equals", "load factor", "resize"],
        "ideal": (
            "A HashMap keeps an array of buckets. When I put a key, it calls hashCode, spreads the "
            "bits, and uses that to pick a bucket index. If two keys land in the same bucket — a "
            "collision — they are chained in that bucket, and the map uses equals to tell them "
            "apart on lookup. Since Java 8, once a bucket gets past about eight entries it converts "
            "the chain into a balanced tree, so worst-case lookup goes from O(n) to O(log n). When "
            "the map is about 75% full, the load factor, it doubles the array and rehashes. That is "
            "why equals and hashCode have to agree: unequal hash codes for equal objects means the "
            "key is looked up in the wrong bucket and never found."
        ),
        "tier": "core",
    },
    {
        "topic": "Collections framework",
        "content": "What is the difference between HashMap and ConcurrentHashMap?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["thread safety", "synchronized", "segment", "bucket lock", "null keys", "Hashtable", "fail-fast"],
        "ideal": (
            "HashMap is not thread-safe — concurrent writes can corrupt it, and in older versions "
            "could even spin forever during a resize. ConcurrentHashMap is safe for concurrent use, "
            "and it gets there by locking only the bucket being written rather than the whole map, "
            "so many threads can write at once as long as they hit different buckets. Reads are "
            "mostly lock-free. Two practical differences: ConcurrentHashMap does not allow null "
            "keys or values, and its iterator is weakly consistent rather than fail-fast, so it "
            "will not throw ConcurrentModificationException. The old alternative, Hashtable, "
            "synchronizes every method and is much slower."
        ),
        "tier": "core",
    },
]

# ─── Core Java: exceptions ────────────────────────────────────────────────────

_EXCEPTIONS: list[BankQuestion] = [
    {
        "topic": "Exception handling",
        "content": "What is the difference between checked and unchecked exceptions? Give an example of each.",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["checked", "unchecked", "compile time", "runtime", "IOException", "NullPointerException", "RuntimeException"],
        "ideal": (
            "Checked exceptions are the ones the compiler forces you to deal with — you either "
            "catch them or declare them with throws. They represent conditions outside your "
            "control that a caller could reasonably recover from, like IOException or "
            "SQLException. Unchecked exceptions extend RuntimeException and the compiler ignores "
            "them; they usually mean a bug in the code, like NullPointerException or "
            "ArrayIndexOutOfBoundsException. The rule of thumb is: checked for something the "
            "caller should handle, unchecked for something the programmer should fix."
        ),
        "tier": "core",
    },
    {
        "topic": "Exception handling",
        "content": "What is the difference between throw and throws?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["throw", "throws", "statement", "declaration", "method signature", "single exception"],
        "ideal": (
            "throw is a statement that actually raises an exception at that point — `throw new "
            "IllegalArgumentException(\"age must be positive\")`. throws is part of a method "
            "signature and declares that this method might raise those exception types, so the "
            "caller knows to handle them. So throw takes one exception object and does something; "
            "throws takes a list of exception classes and only documents and enforces. You use "
            "throw inside the method body and throws next to the method name."
        ),
        "tier": "core",
    },
    {
        "topic": "Exception handling",
        "content": "What is the difference between final, finally and finalize?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["final", "finally", "finalize", "constant", "cleanup", "garbage collector", "deprecated"],
        "ideal": (
            "They are three unrelated things that just look similar. final is a modifier: a final "
            "variable is a constant, a final method cannot be overridden, and a final class cannot "
            "be extended. finally is a block after try-catch that always runs, whether or not an "
            "exception was thrown, so it is where you release resources — though try-with-resources "
            "is better now. finalize was a method the garbage collector called before reclaiming an "
            "object; it was unreliable about when it ran and is deprecated, so nobody should use it."
        ),
        "tier": "core",
    },
]

# ─── Core Java: IO, threads, Java 8 ───────────────────────────────────────────

_MODERN: list[BankQuestion] = [
    {
        "topic": "Input & output",
        "content": "What is the difference between Scanner and BufferedReader for reading input?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["Scanner", "BufferedReader", "parsing", "buffer size", "performance", "synchronized", "nextInt"],
        "ideal": (
            "Scanner is the convenient one — it parses as it reads, so nextInt gives me an int "
            "directly, and it can split on whitespace or a custom delimiter. BufferedReader only "
            "gives me lines as Strings, so I have to parse them myself with Integer.parseInt, but "
            "it is significantly faster because it has a much larger buffer and does no parsing or "
            "regex work. BufferedReader is also synchronized, so it is thread-safe. For competitive "
            "programming or reading large input I use BufferedReader; for small interactive input "
            "Scanner is fine."
        ),
        "tier": "core",
    },
    {
        "topic": "Java 8 & lambdas",
        "content": "What is a lambda expression, and what is a functional interface?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["lambda", "functional interface", "single abstract method", "Runnable", "Predicate", "anonymous class"],
        "ideal": (
            "A lambda is a short way to write a function inline, without declaring a whole class — "
            "for example `(a, b) -> a + b`. It can only be used where a functional interface is "
            "expected, and a functional interface is simply an interface with exactly one abstract "
            "method, which is what tells the compiler what the lambda means. Runnable, Comparator "
            "and Predicate are all functional interfaces, and @FunctionalInterface makes the "
            "compiler enforce the single-method rule. Before Java 8 you would write an anonymous "
            "inner class for the same thing, with about six lines of boilerplate."
        ),
        "tier": "core",
    },
    {
        "topic": "Java 8 & lambdas",
        "content": "What is the Stream API, and what is the difference between an intermediate and a terminal operation?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["Stream", "map", "filter", "collect", "lazy", "terminal", "pipeline", "declarative"],
        "ideal": (
            "Streams let me describe what I want done to a collection rather than writing the loop "
            "— filter, map, sorted, collect. Intermediate operations like filter and map return "
            "another stream and are lazy: nothing actually runs when you call them, they just build "
            "up a pipeline. A terminal operation like collect, forEach or count is what triggers "
            "the whole pipeline to execute, and after it the stream is consumed and cannot be "
            "reused. The laziness matters for performance, because the elements pass through the "
            "whole chain one at a time instead of building an intermediate list at each step."
        ),
        "tier": "core",
    },
    {
        "topic": "Multithreading",
        "content": "What is multithreading, and what are the two ways to create a thread in Java?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["thread", "concurrency", "Thread class", "Runnable", "start", "run", "ExecutorService"],
        "ideal": (
            "Multithreading is running several parts of a program at the same time, so the "
            "application stays responsive and uses multiple cores. The two classic ways are "
            "extending the Thread class and overriding run, or implementing Runnable and passing it "
            "to a Thread. Implementing Runnable is preferred, because Java only allows single class "
            "inheritance so extending Thread uses up your one chance, and Runnable separates the "
            "task from the mechanism that runs it. One thing people get wrong: you call start, not "
            "run — calling run just executes it on the current thread. In real code I would use an "
            "ExecutorService rather than creating threads by hand."
        ),
        "tier": "core",
    },
    {
        "topic": "Multithreading",
        "content": "What is a race condition, and how does the synchronized keyword prevent it?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["race condition", "shared state", "synchronized", "lock", "monitor", "atomic", "volatile"],
        "ideal": (
            "A race condition is when two threads touch shared mutable state at the same time and "
            "the result depends on the timing. The classic example is count++ — it looks like one "
            "step but it is read, add, write, so two threads can both read the same value and one "
            "increment gets lost. synchronized makes a method or block hold a lock on an object, so "
            "only one thread can be inside at a time and the others wait. The trade-off is that "
            "locking costs performance and, done badly, causes deadlock. For a simple counter "
            "AtomicInteger is better, and volatile handles visibility but not atomicity."
        ),
        "tier": "core",
    },
    {
        "topic": "REST APIs",
        "content": "What is a REST API, and what do the main HTTP methods mean?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["REST", "stateless", "resource", "GET", "POST", "PUT", "DELETE", "status code", "idempotent"],
        "ideal": (
            "A REST API exposes data as resources addressed by URLs, and you act on them with "
            "standard HTTP methods. GET reads and should change nothing, POST creates, PUT replaces "
            "or updates, PATCH partially updates, DELETE removes. It is stateless — every request "
            "carries everything the server needs, so the server keeps no session between calls, "
            "which is what makes it easy to scale horizontally. Responses use status codes to say "
            "what happened: 200 for success, 201 created, 400 for a bad request, 401 "
            "unauthenticated, 404 not found, 500 for a server error. GET, PUT and DELETE are "
            "idempotent; POST is not."
        ),
        "tier": "core",
    },
]

# ─── Frameworks: database access ──────────────────────────────────────────────

_DATA_ACCESS: list[BankQuestion] = [
    {
        "topic": "JDBC",
        "content": "What is JDBC, and what are the steps to connect to a database and run a query?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["JDBC", "driver", "DriverManager", "Connection", "PreparedStatement", "ResultSet", "close"],
        "ideal": (
            "JDBC is Java's standard API for talking to relational databases, and each database "
            "ships a driver that implements it, so the same code works against MySQL or Postgres. "
            "The steps are: load the driver, get a Connection from DriverManager with the URL, "
            "username and password, create a Statement or PreparedStatement, execute the query, "
            "read the results out of the ResultSet, and close everything — which is best done with "
            "try-with-resources so it happens even on an exception. I would always use "
            "PreparedStatement rather than string-concatenating the SQL, because it parameterises "
            "the values and that is what prevents SQL injection."
        ),
        "tier": "framework",
    },
    {
        "topic": "JDBC",
        "content": "What is the difference between Statement and PreparedStatement?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["PreparedStatement", "SQL injection", "precompiled", "parameter", "placeholder", "performance"],
        "ideal": (
            "Statement takes a complete SQL string, so building it means concatenating user input "
            "straight into the query — which is exactly how SQL injection happens. "
            "PreparedStatement uses ? placeholders and you set the values separately, so the input "
            "is always treated as data and never as SQL. It is also precompiled by the database, so "
            "running the same query repeatedly with different values is faster. There is no real "
            "reason to prefer Statement; PreparedStatement is safer and usually quicker."
        ),
        "tier": "framework",
    },
    {
        "topic": "Hibernate & JPA",
        "content": "What is the difference between JDBC and Hibernate?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["ORM", "boilerplate", "mapping", "HQL", "caching", "lazy loading", "database independence"],
        "ideal": (
            "JDBC is low-level — I write the SQL, and I map every column to a field by hand, which "
            "is a lot of repetitive code. Hibernate is an ORM: I annotate a class as an entity and "
            "it generates the SQL and does the mapping for me, so saving an object is one call. It "
            "also gives me caching, lazy loading of related entities, and its own query language "
            "HQL that works in terms of objects rather than tables, so switching database is mostly "
            "a config change. The trade-offs are a learning curve, less control over the exact SQL, "
            "and performance traps like the N+1 select problem — so for a very tight, hand-tuned "
            "query I might still drop to JDBC."
        ),
        "tier": "framework",
    },
    {
        "topic": "Hibernate & JPA",
        "content": "What is JPA, and how is it related to Hibernate?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["specification", "implementation", "EntityManager", "Entity", "annotations", "provider", "Spring Data JPA"],
        "ideal": (
            "JPA is a specification — an interface, a set of annotations like @Entity, @Id and "
            "@OneToMany, and the EntityManager API. It does not do anything by itself. Hibernate is "
            "the most common implementation of that specification, so when you use JPA in Spring "
            "Boot, Hibernate is usually the provider doing the work underneath. The reason to code "
            "against JPA rather than Hibernate's own API is portability: you could swap the "
            "provider for EclipseLink without rewriting your entities. Spring Data JPA sits one "
            "level above again and generates repository implementations from interface method "
            "names."
        ),
        "tier": "framework",
    },
]

# ─── Frameworks: Spring ───────────────────────────────────────────────────────

_SPRING: list[BankQuestion] = [
    {
        "topic": "Spring Boot",
        "content": "What is Spring Boot, and what problem does it solve compared to plain Spring?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["auto configuration", "starter", "embedded server", "convention over configuration", "opinionated", "XML"],
        "ideal": (
            "Plain Spring is powerful but needs a lot of setup — XML or Java config, a servlet "
            "container to deploy a WAR into, and you wire up every dependency yourself. Spring Boot "
            "is opinionated defaults on top of it: auto-configuration looks at what is on the "
            "classpath and configures it for you, starter dependencies pull in a consistent set of "
            "libraries with one entry, and an embedded Tomcat means the application is a runnable "
            "jar rather than something you deploy. So a REST service is a main method, one "
            "annotation and a controller, instead of a day of configuration."
        ),
        "tier": "framework",
    },
    {
        "topic": "Spring Boot",
        "content": "What is dependency injection, and why is it better than creating objects with new?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["dependency injection", "IoC", "container", "constructor injection", "loose coupling", "testability", "@Autowired"],
        "ideal": (
            "Dependency injection means a class does not build its own dependencies — it declares "
            "what it needs and something else supplies them. In Spring that something is the IoC "
            "container: it creates the beans and passes them in. The reason it beats `new` is "
            "coupling. If my service does `new MySqlUserRepository()` it is welded to that class, "
            "but if it takes a UserRepository in its constructor I can pass a different "
            "implementation, or a mock in a unit test, without touching the service. Constructor "
            "injection is the preferred style because the dependency is required and the object is "
            "never in a half-built state; field injection with @Autowired hides it."
        ),
        "tier": "framework",
    },
    {
        "topic": "Spring REST",
        "content": "How do you build a REST endpoint in Spring Boot? Explain the main annotations.",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["@RestController", "@RequestMapping", "@GetMapping", "@PathVariable", "@RequestBody", "ResponseEntity", "@Service"],
        "ideal": (
            "I put @RestController on the class, which marks it as a controller whose return values "
            "become the response body rather than a view name. @RequestMapping on the class sets the "
            "base path, and then @GetMapping, @PostMapping and so on map individual methods. "
            "@PathVariable pulls a value out of the URL, @RequestParam reads a query parameter, and "
            "@RequestBody deserialises the JSON body into an object. Returning ResponseEntity lets "
            "me set the status code and headers explicitly rather than always getting 200. The "
            "controller should stay thin — validate the input, call a @Service, return the result."
        ),
        "tier": "framework",
    },
    {
        "topic": "Spring REST",
        "content": "What does Jackson do in a Spring Boot application?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["Jackson", "serialization", "deserialization", "JSON", "ObjectMapper", "@JsonProperty", "@JsonIgnore"],
        "ideal": (
            "Jackson is the library that converts between Java objects and JSON, and Spring Boot "
            "auto-configures it, which is why returning an object from a @RestController method "
            "just produces JSON. Serialization is object to JSON, deserialization is JSON to "
            "object, and ObjectMapper is the class doing it if I need to call it directly. The "
            "annotations I reach for most are @JsonProperty to rename a field, @JsonIgnore to keep "
            "something out of the response — a password field, for instance — and "
            "@JsonInclude(NON_NULL) to drop nulls. It needs a no-argument constructor and getters "
            "to work by default, which is one reason entities have them."
        ),
        "tier": "framework",
    },
]

# ─── Core Java: design principles and patterns ────────────────────────────────

_DESIGN: list[BankQuestion] = [
    {
        "topic": "SOLID principles",
        "content": "What does SOLID stand for, and can you explain any two of the principles?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["single responsibility", "open closed", "Liskov", "interface segregation", "dependency inversion"],
        "ideal": (
            "SOLID is five design principles. S is single responsibility — a class "
            "should have one reason to change. O is open-closed — open for "
            "extension, closed for modification, so you add behaviour by adding a "
            "class rather than editing an existing one. L is Liskov substitution — "
            "a subclass must work anywhere its parent does without surprising the "
            "caller. I is interface segregation — many small interfaces beat one "
            "large one, so nobody implements methods they do not need. D is "
            "dependency inversion — depend on an abstraction, not a concrete "
            "class, which is exactly what Spring's dependency injection gives you."
        ),
        "tier": "core",
    },
    {
        "topic": "SOLID principles",
        "content": "What is the single responsibility principle, and what goes wrong without it?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["one reason to change", "cohesion", "coupling", "testability", "god class"],
        "ideal": (
            "A class should have one responsibility, so only one kind of change "
            "makes you edit it. Without it you get a god class that does "
            "validation, database access and formatting all at once — every "
            "feature touches it, so every change risks breaking something "
            "unrelated, it is hard to test because you cannot exercise one part in "
            "isolation, and two developers editing it conflict constantly. The "
            "practical test I use is whether I can describe what the class does in "
            "one sentence without saying \"and\"."
        ),
        "tier": "core",
    },
    {
        "topic": "Design patterns",
        "content": "What is the singleton pattern, and how would you implement one safely in Java?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["single instance", "private constructor", "static", "thread safety", "enum", "double-checked locking"],
        "ideal": (
            "A singleton guarantees exactly one instance of a class and gives you a "
            "global way to reach it — a configuration holder or a connection pool, "
            "for example. You make the constructor private and expose a static "
            "accessor. The catch is thread safety: two threads can both see a null "
            "instance and both create one, so you need either eager static "
            "initialisation, or double-checked locking with a volatile field. The "
            "cleanest way in Java is actually a single-element enum, because the "
            "JVM guarantees the instance and it is serialisation-safe. Worth saying "
            "that singletons make testing harder, so in Spring I would just use a "
            "singleton-scoped bean and let the container manage it."
        ),
        "tier": "core",
    },
    {
        "topic": "Design patterns",
        "content": "Which design patterns have you actually used, and what problem did each solve?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["factory", "builder", "singleton", "observer", "strategy", "adapter", "MVC"],
        "ideal": (
            "The ones I have genuinely used are factory, builder and strategy. "
            "Factory when the caller should not know which concrete class it gets — "
            "a payment handler chosen by payment type. Builder for objects with "
            "many optional fields, so I get readable construction instead of a "
            "six-argument constructor; StringBuilder and Stream.collect are both "
            "this. Strategy to swap an algorithm at runtime — different sorting or "
            "pricing rules behind one interface, which is also the open-closed "
            "principle in practice. I have used observer indirectly through event "
            "listeners, and MVC is the shape of every Spring web app: controller, "
            "service, view."
        ),
        "tier": "core",
    },
    {
        "topic": "Design patterns",
        "content": "What is the difference between the factory pattern and the builder pattern?",
        "difficulty": "medium",
        "type": "conceptual",
        "keywords": ["which class", "how to construct", "optional fields", "immutable", "readability"],
        "ideal": (
            "Factory decides WHICH class to create — the caller asks for a shape "
            "and gets a Circle or a Square without knowing the concrete type. "
            "Builder decides HOW to construct ONE class when it has many optional "
            "fields; you chain setters and call build(). So factory hides the type, "
            "builder hides the assembly. You reach for builder when a constructor "
            "would take five arguments and nobody can remember the order, and it "
            "also lets you produce an immutable object because everything is set "
            "before build() returns."
        ),
        "tier": "core",
    },
]

#: The whole bank, in the order a real interview would move through it: platform,
#: language, then frameworks.
JAVA_QUESTION_BANK: list[BankQuestion] = [
    *_PLATFORM,
    *_STRINGS,
    *_OOP,
    *_COLLECTIONS,
    *_EXCEPTIONS,
    *_DESIGN,
    *_MODERN,
    *_DATA_ACCESS,
    *_SPRING,
]

#: Topics whose questions only make sense for a Java backend or full-stack role.
#: Everything else is fair game at any company on the catalogue.
FRAMEWORK_TOPICS: frozenset[str] = frozenset(
    q["topic"] for q in JAVA_QUESTION_BANK if q["tier"] == "framework"
)

#: Every distinct topic, for the planner prompt and for coverage tests.
ALL_TOPICS: tuple[str, ...] = tuple(dict.fromkeys(q["topic"] for q in JAVA_QUESTION_BANK))


def _wants_frameworks(track_name: str, program: str) -> bool:
    """
    Should this interview include Spring/JPA/Hibernate/Jackson questions?

    Yes for anything that names a backend, full-stack or Java specialisation.
    No for an aptitude-first mass-recruiter round, where a Spring question burns
    one of twelve slots on something the candidate will not be asked.

    Deliberately a keyword match rather than a company allowlist: the catalogue
    has twelve companies and dozens of programs, and a candidate can type any
    company name at all. Matching on what the ROLE says avoids maintaining a list
    that is wrong the moment a new program appears.
    """
    haystack = f"{track_name} {program}".lower()
    return any(
        kw in haystack
        for kw in (
            "java",
            "fse",
            "full stack",
            "full-stack",
            "fullstack",
            "backend",
            "back end",
            "back-end",
            "spring",
            "software engineer",
            "sde",
            "developer",
            "power programmer",
            "digital specialist",
        )
    )


def for_track(track_name: str = "", program: str = "") -> list[BankQuestion]:
    """
    The questions worth asking for this role.

    Core Java always; frameworks only when the role is a Java/backend one.
    """
    if _wants_frameworks(track_name, program):
        return list(JAVA_QUESTION_BANK)
    return [q for q in JAVA_QUESTION_BANK if q["tier"] == "core"]


def topics_for_track(track_name: str = "", program: str = "") -> list[str]:
    """Distinct topic names for this role, in bank order."""
    return list(dict.fromkeys(q["topic"] for q in for_track(track_name, program)))
