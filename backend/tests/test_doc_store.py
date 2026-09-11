"""The file a customer is currently talking about (task 15.1).

What these guard is the one thing that makes a document different from a photo:
it has to still be there on the next question, and it has to eventually not be.
"""
from app.services import doc_store
from app.services.llm import Document


def _document(name: str) -> Document:
    return Document(data=b"%PDF-" + name.encode(), filename=name, marker=f"[document] {name}")


def test_the_file_is_still_there_on_the_next_question():
    """The whole reason this store exists. A menu is sent once and asked about
    three times; an attachment that expired with its turn would answer the
    second question with "I cannot see it"."""
    doc_store.remember("60111", _document("menu.pdf"))

    assert doc_store.get("60111").filename == "menu.pdf"
    assert doc_store.get("60111").filename == "menu.pdf"


def test_a_second_file_replaces_the_first():
    """"The file we are talking about" is singular in every conversation this
    demo has. Keeping both would mean deciding which one a question is about."""
    doc_store.remember("60222", _document("menu.pdf"))
    doc_store.remember("60222", _document("price-list.pdf"))

    assert doc_store.get("60222").filename == "price-list.pdf"


def test_one_customers_file_is_not_another_customers():
    doc_store.remember("60333", _document("mine.pdf"))

    assert doc_store.get("60444") is None


def test_starting_the_demo_over_drops_it():
    doc_store.remember("60555", _document("menu.pdf"))

    doc_store.forget("60555")

    assert doc_store.get("60555") is None


def test_the_oldest_file_goes_rather_than_memory_growing_without_end():
    """Megabytes each, in a process that runs for weeks. The cap is the only
    thing between a month of strangers and a resident gigabyte."""
    for n in range(doc_store.MAX_DOCUMENTS + 1):
        doc_store.remember(f"6060{n}", _document(f"{n}.pdf"))

    assert doc_store.get("60600") is None
    assert doc_store.get(f"6060{doc_store.MAX_DOCUMENTS}") is not None


def test_asking_about_a_file_is_what_keeps_it_alive():
    """Least recently *used*, not least recently sent: a customer three
    questions into their own PDF must not lose it to someone who just walked in."""
    for n in range(doc_store.MAX_DOCUMENTS):
        doc_store.remember(f"6070{n}", _document(f"{n}.pdf"))
    doc_store.get("60700")

    doc_store.remember("60799", _document("newcomer.pdf"))

    assert doc_store.get("60700") is not None
    assert doc_store.get("60701") is None
