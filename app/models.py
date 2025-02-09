from sqlalchemy import Column, Integer, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from app.database import Base

class Project(Base):
    __tablename__ = "2024_25"  # Repeat similar classes for other years
    
    group_no = Column(Integer, primary_key=True)
    usn = Column(ARRAY(Text), nullable=False)
    name = Column(ARRAY(Text), nullable=False)
    project_title = Column(Text, nullable=False)
    guide_name = Column(Text, nullable=False)
    outcomes = Column(Text)
    proof_link = Column(Text)
    search_vector = Column(TSVECTOR)