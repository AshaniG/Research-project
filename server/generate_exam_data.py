#!/usr/bin/env python3
"""
generate_exam_data.py - Build a synthetic "exam results" dataset for the
victim server (server/exam_portal.py) to serve.

This gives the DDoS-detection lab a *realistic* target: instead of attacking an
empty "server alive" page, the attacker floods an exam-results web portal while
the XDP/eBPF detector protects it. All data here is randomly generated and
fictional — no real students.

Usage:
    python3 server/generate_exam_data.py                 # -> server/exam_results.json
    python3 server/generate_exam_data.py -n 500 -o out.json
    from generate_exam_data import generate               # returns list[dict]
"""
import argparse
import json
import os
import random

# --- Fictional name pools (mixed international) ---------------------------
FIRST_NAMES = [
    "Ava", "Liam", "Noah", "Emma", "Olivia", "Sanduni", "Kavindu", "Tharindu",
    "Nimesha", "Ishara", "Ravindu", "Dineth", "Hasini", "Amaya", "Sachin",
    "Wei", "Mei", "Arjun", "Priya", "Rahul", "Fatima", "Omar", "Yuki",
    "Hana", "Leo", "Mia", "Ethan", "Zara", "Ali", "Sofia", "Lucas", "Chloe",
]
LAST_NAMES = [
    "Fernando", "Perera", "Silva", "Jayawardena", "Bandara", "Wickramasinghe",
    "Gunawardena", "Rajapaksa", "Dissanayake", "Smith", "Johnson", "Lee",
    "Kim", "Patel", "Sharma", "Chen", "Wang", "Garcia", "Nguyen", "Khan",
    "Ahmed", "Tanaka", "Muller", "Brown", "Wilson",
]

# --- Course catalogue -----------------------------------------------------
PROGRAMS = [
    "BSc Computer Science",
    "BSc Software Engineering",
    "BSc Information Systems",
    "BSc Data Science",
]

SUBJECTS = [
    ("CS2010", "Data Structures & Algorithms"),
    ("CS2020", "Computer Networks"),
    ("CS3010", "Operating Systems"),
    ("CS3020", "Database Systems"),
    ("CS3030", "Cyber Security"),
    ("CS3040", "Machine Learning"),
    ("CS3050", "Software Architecture"),
    ("MA2010", "Discrete Mathematics"),
    ("MA2020", "Probability & Statistics"),
    ("EN1010", "Technical Communication"),
]

# --- Grading scale: (min_marks, grade, grade_point) ----------------------
GRADE_SCALE = [
    (85, "A+", 4.0),
    (75, "A",  4.0),
    (70, "A-", 3.7),
    (65, "B+", 3.3),
    (60, "B",  3.0),
    (55, "B-", 2.7),
    (50, "C+", 2.3),
    (45, "C",  2.0),
    (40, "C-", 1.7),
    (35, "D",  1.0),
    (0,  "F",  0.0),
]


def marks_to_grade(marks):
    """Return (grade_letter, grade_point) for a numeric mark."""
    for threshold, grade, point in GRADE_SCALE:
        if marks >= threshold:
            return grade, point
    return "F", 0.0


def generate(n=200, seed=42):
    """Generate `n` fictional student records with exam results.

    Deterministic for a given seed so runs are reproducible.
    """
    rng = random.Random(seed)
    students = []
    for i in range(1, n + 1):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        program = rng.choice(PROGRAMS)
        year = rng.randint(1, 4)
        enroll_year = 2026 - year

        # Each student sits 5-6 subjects.
        chosen = rng.sample(SUBJECTS, rng.randint(5, 6))
        results = []
        total_points = 0.0
        for code, name in chosen:
            # Bias marks toward a realistic bell-ish spread (35-95).
            marks = max(0, min(100, int(rng.gauss(65, 15))))
            grade, point = marks_to_grade(marks)
            total_points += point
            results.append(
                {"code": code, "subject": name, "marks": marks, "grade": grade}
            )
        gpa = round(total_points / len(results), 2)

        students.append(
            {
                "student_id": f"S{i:04d}",
                "index_no": f"{enroll_year}{program.split()[1][:2].upper()}{i:04d}",
                "name": f"{first} {last}",
                "program": program,
                "year": year,
                "gpa": gpa,
                "results": results,
            }
        )
    return students


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="Generate synthetic exam-results data.")
    ap.add_argument("-n", "--count", type=int, default=200,
                    help="number of students to generate (default 200)")
    ap.add_argument("-o", "--out", default=os.path.join(here, "exam_results.json"),
                    help="output JSON path (default server/exam_results.json)")
    ap.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    args = ap.parse_args()

    students = generate(args.count, args.seed)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(students, f, indent=2)
    print(f"Wrote {len(students)} student records to {args.out}")


if __name__ == "__main__":
    main()
