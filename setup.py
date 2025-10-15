#!/usr/bin/env python3
"""Setup script for ProofOfThought.

This setup.py is provided for backward compatibility.
Modern installations should use pyproject.toml with pip install.
"""


# Read version from package
__version__ = "1.0.0"

# Read long description from README
with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

#  To be completed

# setup(
#     name="proofofthought",
#     version=__version__,
#     description="LLM-based reasoning using Z3 theorem proving",
#     long_description=long_description,
#     long_description_content_type="text/markdown",
#     author="Debargha Ganguly",
#     author_email="debargha@case.edu",
#     url="https://github.com/debarghaG/proofofthought",
#     license="MIT",
#     packages=find_packages(exclude=["tests", "tests.*", "examples", "examples.*"]),
#     python_requires=">=3.12",
#     install_requires=[
#         "z3-solver>=4.15.0",
#         "openai>=2.0.0",
#         "scikit-learn>=1.7.0",
#         "numpy>=2.3.0",
#         "python-dotenv>=1.0.0",
#     ],
#     extras_require={
#         "dev": [
#             "black>=25.9.0",
#             "ruff>=0.13.0",
#             "mypy>=1.18.0",
#             "pre-commit>=4.3.0",
#             "pytest>=8.0.0",
#         ],
#     },
#     classifiers=[
#         "Development Status :: 4 - Beta",
#         "Intended Audience :: Developers",
#         "Intended Audience :: Science/Research",
#         "License :: OSI Approved :: MIT License",
#         "Programming Language :: Python :: 3",
#         "Programming Language :: Python :: 3.12",
#         "Topic :: Scientific/Engineering :: Artificial Intelligence",
#         "Topic :: Software Development :: Libraries :: Python Modules",
#     ],
#     keywords="llm reasoning z3 theorem-proving smt ai",
#     project_urls={
#         "Documentation": "https://github.com/debarghaG/proofofthought#readme",
#         "Source": "https://github.com/debarghaG/proofofthought",
#         "Bug Tracker": "https://github.com/debarghaG/proofofthought/issues",
#     },
# )
