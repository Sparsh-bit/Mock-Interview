"""
Curated MCQ bank — app/data/quiz_bank.py

A hand-written set of common fresher-interview multiple-choice questions,
grouped by topic. Served instantly (no AI call) by the /quiz/bank endpoints,
so it stays fast and reliable under concurrent load. Each attempt randomly
samples from this pool, so repeats vary.

Each item: question, options[4], correct_index (0-3), explanation, difficulty.

`difficulty` is REQUIRED — "easy" | "medium" | "hard". The quiz endpoint has always
read it (`q.get("difficulty", "medium")`) but nothing in the bank ever set it, so
every question in the product reported itself as medium and the easy/hard
distinction did not exist. tests/test_quiz_bank.py fails if any item omits it.
"""

from __future__ import annotations

from app.data.quiz_bank_java import JAVA_QUIZ_BANK

_GENERAL_BANK: dict[str, list[dict]] = {
    "Core Java & OOP": [
        {
            "question": "Which of these is NOT a pillar of Object-Oriented Programming?",
            "options": ["Encapsulation", "Inheritance", "Compilation", "Polymorphism"],
            "correct_index": 2,
            "explanation": "The four OOP pillars are Encapsulation, Inheritance, Polymorphism, and Abstraction. Compilation is a build step, not an OOP principle.",
            "difficulty": "easy",
        },
        {
            "question": "In Java, which keyword prevents a class from being subclassed?",
            "options": ["static", "final", "sealed", "private"],
            "correct_index": 1,
            "explanation": "A `final` class cannot be extended. (`sealed` restricts which classes may extend, but does not forbid subclassing outright.)",
            "difficulty": "easy",
        },
        {
            "question": "What is the size of an `int` in Java?",
            "options": ["16 bits", "32 bits", "64 bits", "Platform dependent"],
            "correct_index": 1,
            "explanation": "Java's `int` is always 32 bits (4 bytes), independent of platform — one of Java's portability guarantees.",
            "difficulty": "easy",
        },
        {
            "question": "Which method must be overridden alongside equals() for correct HashMap behavior?",
            "options": ["toString()", "compareTo()", "hashCode()", "clone()"],
            "correct_index": 2,
            "explanation": "The equals/hashCode contract: equal objects must have equal hash codes, so overriding equals() without hashCode() breaks hash-based collections.",
            "difficulty": "medium",
        },
        {
            "question": "What does the `static` keyword mean for a method?",
            "options": [
                "It belongs to the class, not an instance",
                "It cannot be called",
                "It is thread-safe",
                "It runs only once",
            ],
            "correct_index": 0,
            "explanation": "A static method belongs to the class and can be called without creating an instance.",
            "difficulty": "easy",
        },
        {
            "question": "Which is true about an abstract class in Java?",
            "options": [
                "It can be instantiated directly",
                "It cannot have constructors",
                "It can have both abstract and concrete methods",
                "All its methods must be abstract",
            ],
            "correct_index": 2,
            "explanation": "An abstract class can mix abstract methods (no body) and concrete methods, can have constructors, but cannot be instantiated directly.",
            "difficulty": "medium",
        },
        {
            "question": "What is method overloading?",
            "options": [
                "Same method name, different parameter lists in the same class",
                "A subclass redefining a superclass method",
                "Calling a method too many times",
                "A method that calls itself",
            ],
            "correct_index": 0,
            "explanation": "Overloading = same name, different parameters (compile-time polymorphism). Overriding is the subclass redefinition; recursion is self-calling.",
            "difficulty": "easy",
        },
        {
            "question": "Which access modifier makes a member visible only within its own class?",
            "options": ["protected", "public", "private", "default (package)"],
            "correct_index": 2,
            "explanation": "`private` restricts visibility to the declaring class. `protected` adds subclasses/package; default is package-only; public is everywhere.",
            "difficulty": "easy",
        },
    ],
    "Data Structures & Algorithms": [
        {
            "question": "What is the average time complexity of a lookup in a hash table?",
            "options": ["O(1)", "O(log n)", "O(n)", "O(n log n)"],
            "correct_index": 0,
            "explanation": "Hash-table lookup is O(1) on average; worst case is O(n) with many collisions.",
            "difficulty": "easy",
        },
        {
            "question": "Which data structure uses LIFO (Last In, First Out) ordering?",
            "options": ["Queue", "Stack", "Linked list", "Binary tree"],
            "correct_index": 1,
            "explanation": "A stack is LIFO. A queue is FIFO (First In, First Out).",
            "difficulty": "easy",
        },
        {
            "question": "What is the time complexity of binary search on a sorted array of n elements?",
            "options": ["O(n)", "O(log n)", "O(1)", "O(n^2)"],
            "correct_index": 1,
            "explanation": "Binary search halves the search space each step, giving O(log n). It requires the array to be sorted.",
            "difficulty": "easy",
        },
        {
            "question": "Which sorting algorithm has O(n log n) worst-case time and is stable?",
            "options": ["Quick sort", "Merge sort", "Bubble sort", "Selection sort"],
            "correct_index": 1,
            "explanation": "Merge sort is O(n log n) worst-case and stable. Quicksort is O(n^2) worst-case; bubble/selection are O(n^2).",
            "difficulty": "medium",
        },
        {
            "question": "What does a queue's `dequeue` operation do?",
            "options": [
                "Removes the most recently added element",
                "Removes the oldest (front) element",
                "Adds an element to the back",
                "Peeks without removing",
            ],
            "correct_index": 1,
            "explanation": "A queue is FIFO; dequeue removes from the front (the oldest element).",
            "difficulty": "easy",
        },
        {
            "question": "Which structure is best for implementing a priority queue efficiently?",
            "options": ["Array", "Binary heap", "Linked list", "Hash table"],
            "correct_index": 1,
            "explanation": "A binary heap gives O(log n) insert and extract-min/max, ideal for priority queues.",
            "difficulty": "medium",
        },
        {
            "question": "What is the space complexity of an adjacency matrix for a graph with V vertices?",
            "options": ["O(V)", "O(V + E)", "O(V^2)", "O(E)"],
            "correct_index": 2,
            "explanation": "An adjacency matrix stores a V×V grid, so O(V^2) regardless of edge count. An adjacency list is O(V + E).",
            "difficulty": "medium",
        },
        {
            "question": "Which traversal visits a binary tree's root between its left and right subtrees?",
            "options": ["Pre-order", "In-order", "Post-order", "Level-order"],
            "correct_index": 1,
            "explanation": "In-order = left, root, right (yields sorted order for a BST). Pre-order visits root first; post-order visits root last.",
            "difficulty": "medium",
        },
    ],
    "SQL & Databases": [
        {
            "question": "Which SQL clause filters rows BEFORE grouping?",
            "options": ["HAVING", "WHERE", "GROUP BY", "ORDER BY"],
            "correct_index": 1,
            "explanation": "WHERE filters rows before aggregation; HAVING filters groups after GROUP BY.",
            "difficulty": "medium",
        },
        {
            "question": "What does a PRIMARY KEY guarantee?",
            "options": [
                "Values can repeat",
                "Uniqueness and non-null for the column(s)",
                "Automatic sorting",
                "Foreign relationships",
            ],
            "correct_index": 1,
            "explanation": "A primary key enforces uniqueness and NOT NULL, uniquely identifying each row.",
            "difficulty": "easy",
        },
        {
            "question": "Which JOIN returns only rows with matching keys in both tables?",
            "options": ["LEFT JOIN", "RIGHT JOIN", "INNER JOIN", "FULL OUTER JOIN"],
            "correct_index": 2,
            "explanation": "INNER JOIN returns only matched rows. LEFT/RIGHT/FULL keep unmatched rows from one or both sides.",
            "difficulty": "easy",
        },
        {
            "question": "What does the ACID 'I' stand for in database transactions?",
            "options": ["Integrity", "Isolation", "Indexing", "Inheritance"],
            "correct_index": 1,
            "explanation": "ACID = Atomicity, Consistency, Isolation, Durability. Isolation means concurrent transactions don't interfere.",
            "difficulty": "medium",
        },
        {
            "question": "Which normal form eliminates transitive dependencies?",
            "options": ["1NF", "2NF", "3NF", "BCNF"],
            "correct_index": 2,
            "explanation": "3NF removes transitive dependencies (non-key attributes depending on other non-key attributes).",
            "difficulty": "hard",
        },
        {
            "question": "What is the purpose of an index in a database?",
            "options": [
                "To enforce foreign keys",
                "To speed up data retrieval at the cost of write speed/space",
                "To encrypt data",
                "To normalize tables",
            ],
            "correct_index": 1,
            "explanation": "An index speeds reads/lookups but adds overhead on writes and consumes storage.",
            "difficulty": "easy",
        },
    ],
    "DBMS & OS": [
        {
            "question": "What is a deadlock?",
            "options": [
                "A process using 100% CPU",
                "Two+ processes each waiting for a resource the other holds",
                "A crashed process",
                "A process with no memory",
            ],
            "correct_index": 1,
            "explanation": "Deadlock: processes are stuck in a circular wait, each holding a resource the other needs.",
            "difficulty": "easy",
        },
        {
            "question": "What is the difference between a process and a thread?",
            "options": [
                "They are identical",
                "A thread has its own memory space; a process shares memory",
                "Threads share the process's memory; processes have separate memory",
                "A process is faster than a thread",
            ],
            "correct_index": 2,
            "explanation": "Threads within a process share its address space; separate processes have isolated memory.",
            "difficulty": "easy",
        },
        {
            "question": "Which scheduling algorithm can cause starvation of long jobs?",
            "options": ["FCFS", "Round Robin", "Shortest Job First", "FIFO"],
            "correct_index": 2,
            "explanation": "SJF favors short jobs, so a steady stream of them can starve long jobs indefinitely.",
            "difficulty": "hard",
        },
        {
            "question": "What is virtual memory?",
            "options": [
                "RAM installed on the GPU",
                "An abstraction letting programs use more memory than physical RAM via disk paging",
                "Cache memory",
                "Read-only memory",
            ],
            "correct_index": 1,
            "explanation": "Virtual memory uses disk (paging/swapping) to give each process a large contiguous address space beyond physical RAM.",
            "difficulty": "medium",
        },
        {
            "question": "What does 'thrashing' refer to in an OS?",
            "options": [
                "Excessive paging that cripples performance",
                "CPU overheating",
                "Disk fragmentation",
                "Deadlock resolution",
            ],
            "correct_index": 0,
            "explanation": "Thrashing is when the system spends more time paging memory in/out than executing, collapsing throughput.",
            "difficulty": "hard",
        },
        {
            "question": "In DBMS, what does a 'foreign key' establish?",
            "options": [
                "A unique row identifier",
                "A link/referential integrity between two tables",
                "An encrypted column",
                "An auto-incrementing value",
            ],
            "correct_index": 1,
            "explanation": "A foreign key references another table's primary key, enforcing referential integrity.",
            "difficulty": "easy",
        },
    ],
    "Computer Networks": [
        {
            "question": "Which layer of the OSI model does the IP protocol operate at?",
            "options": ["Transport", "Network", "Data Link", "Application"],
            "correct_index": 1,
            "explanation": "IP is a Network-layer (Layer 3) protocol handling addressing and routing.",
            "difficulty": "medium",
        },
        {
            "question": "What is the main difference between TCP and UDP?",
            "options": [
                "TCP is connectionless; UDP is connection-oriented",
                "TCP is reliable/ordered; UDP is faster but unreliable",
                "They are the same",
                "UDP guarantees delivery; TCP does not",
            ],
            "correct_index": 1,
            "explanation": "TCP provides reliable, ordered, connection-oriented delivery; UDP is connectionless, faster, with no delivery guarantee.",
            "difficulty": "easy",
        },
        {
            "question": "What does DNS do?",
            "options": [
                "Encrypts web traffic",
                "Resolves domain names to IP addresses",
                "Assigns IP addresses dynamically",
                "Routes packets between networks",
            ],
            "correct_index": 1,
            "explanation": "DNS translates human-readable domain names (example.com) into IP addresses. DHCP assigns IPs; routers route.",
            "difficulty": "easy",
        },
        {
            "question": "Which HTTP status code means 'Not Found'?",
            "options": ["200", "301", "404", "500"],
            "correct_index": 2,
            "explanation": "404 = resource not found. 200 = OK, 301 = moved permanently, 500 = server error.",
            "difficulty": "easy",
        },
        {
            "question": "What is the purpose of the TCP three-way handshake?",
            "options": [
                "To encrypt the connection",
                "To establish a reliable connection (SYN, SYN-ACK, ACK)",
                "To close a connection",
                "To assign an IP address",
            ],
            "correct_index": 1,
            "explanation": "SYN → SYN-ACK → ACK synchronizes sequence numbers and establishes the connection before data transfer.",
            "difficulty": "medium",
        },
    ],
    "Aptitude & Reasoning": [
        {
            "question": "If a train travels 60 km in 45 minutes, what is its speed in km/h?",
            "options": ["75 km/h", "80 km/h", "90 km/h", "60 km/h"],
            "correct_index": 1,
            "explanation": "45 min = 0.75 h. Speed = 60 / 0.75 = 80 km/h.",
            "difficulty": "easy",
        },
        {
            "question": "What is 15% of 240?",
            "options": ["36", "32", "40", "24"],
            "correct_index": 0,
            "explanation": "15% of 240 = 240 x 0.15 = 36. The quick mental route is 10% (24) plus half of that (12), which is 36 — faster than long multiplication under time pressure.",
            "difficulty": "easy",
        },
        {
            "question": "Find the next number: 2, 6, 12, 20, 30, ?",
            "options": ["40", "42", "38", "44"],
            "correct_index": 1,
            "explanation": "Differences are 4, 6, 8, 10, 12 → next term = 30 + 12 = 42 (n(n+1) pattern).",
            "difficulty": "medium",
        },
        {
            "question": "If all Bloops are Razzies and all Razzies are Lazzies, then all Bloops are definitely:",
            "options": ["Not Lazzies", "Lazzies", "Razzies only", "Cannot be determined"],
            "correct_index": 1,
            "explanation": "Transitive: Bloops → Razzies → Lazzies, so all Bloops are Lazzies.",
            "difficulty": "easy",
        },
        {
            "question": "A man buys an item for ₹80 and sells it for ₹100. What is his profit percentage?",
            "options": ["20%", "25%", "10%", "15%"],
            "correct_index": 1,
            "explanation": "Profit = 20 on cost 80 → 20/80 × 100 = 25%.",
            "difficulty": "easy",
        },
        {
            "question": "Which number is a prime?",
            "options": ["51", "57", "59", "63"],
            "correct_index": 2,
            "explanation": "59 is prime. 51 = 3×17, 57 = 3×19, 63 = 7×9.",
            "difficulty": "easy",
        },
    ],
}

#: The bank the API serves. Java/Spring topics come from quiz_bank_java.py — kept
#: in their own module because they are the bulk of the content and reviewing a
#: 60-question diff inside a 40-question file is how mistakes get missed.
QUIZ_BANK: dict[str, list[dict]] = {**_GENERAL_BANK, **JAVA_QUIZ_BANK}
