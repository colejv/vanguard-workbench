# Creating data in a data store using a dynamic ontology

<!-- source: https://patents.google.com/patent/US9589014B2/en -->

US9589014B2 - Creating data in a data store using a dynamic ontology - Google Patents
Creating data in a data store using a dynamic ontology Download PDFInfo
- Publication number
- US9589014B2 US9589014B2 US14/954,680 US201514954680A US9589014B2 US 9589014 B2 US9589014 B2 US 9589014B2 US 201514954680 A US201514954680 A US 201514954680A US 9589014 B2 US9589014 B2 US 9589014B2
- Authority
- US
- United States
- Prior art keywords
- data
- parser
- property
- input data
- definitions
- Prior art date
- Legal status (The legal status is an assumption and is not a legal conclusion. Google has not performed a legal analysis and makes no representation as to the accuracy of the status listed.)
- Active
Links
Images
Classifications
- 
        - G—PHYSICS
- G06—COMPUTING OR CALCULATING; COUNTING
- G06F—ELECTRIC DIGITAL DATA PROCESSING
- G06F16/00—Information retrieval; Database structures therefor; File system structures therefor
- G06F16/20—Information retrieval; Database structures therefor; File system structures therefor of structured data, e.g. relational data
- G06F16/22—Indexing; Data structures therefor; Storage structures
- G06F16/2219—Large Object storage; Management thereof
 
- 
        - G06F17/30424—
 
- 
        - G—PHYSICS
- G06—COMPUTING OR CALCULATING; COUNTING
- G06F—ELECTRIC DIGITAL DATA PROCESSING
- G06F16/00—Information retrieval; Database structures therefor; File system structures therefor
- G06F16/20—Information retrieval; Database structures therefor; File system structures therefor of structured data, e.g. relational data
- G06F16/21—Design, administration or maintenance of databases
 
- 
        - G—PHYSICS
- G06—COMPUTING OR CALCULATING; COUNTING
- G06F—ELECTRIC DIGITAL DATA PROCESSING
- G06F16/00—Information retrieval; Database structures therefor; File system structures therefor
- G06F16/20—Information retrieval; Database structures therefor; File system structures therefor of structured data, e.g. relational data
- G06F16/21—Design, administration or maintenance of databases
- G06F16/211—Schema design and management
- G06F16/213—Schema design and management with details for schema evolution support
 
- 
        - G—PHYSICS
- G06—COMPUTING OR CALCULATING; COUNTING
- G06F—ELECTRIC DIGITAL DATA PROCESSING
- G06F16/00—Information retrieval; Database structures therefor; File system structures therefor
- G06F16/20—Information retrieval; Database structures therefor; File system structures therefor of structured data, e.g. relational data
- G06F16/22—Indexing; Data structures therefor; Storage structures
 
- 
        - G—PHYSICS
- G06—COMPUTING OR CALCULATING; COUNTING
- G06F—ELECTRIC DIGITAL DATA PROCESSING
- G06F16/00—Information retrieval; Database structures therefor; File system structures therefor
- G06F16/20—Information retrieval; Database structures therefor; File system structures therefor of structured data, e.g. relational data
- G06F16/23—Updating
- G06F16/2365—Ensuring data consistency and integrity
 
- 
        - G—PHYSICS
- G06—COMPUTING OR CALCULATING; COUNTING
- G06F—ELECTRIC DIGITAL DATA PROCESSING
- G06F16/00—Information retrieval; Database structures therefor; File system structures therefor
- G06F16/20—Information retrieval; Database structures therefor; File system structures therefor of structured data, e.g. relational data
- G06F16/24—Querying
- G06F16/245—Query processing
 
- 
        - G—PHYSICS
- G06—COMPUTING OR CALCULATING; COUNTING
- G06F—ELECTRIC DIGITAL DATA PROCESSING
- G06F16/00—Information retrieval; Database structures therefor; File system structures therefor
- G06F16/30—Information retrieval; Database structures therefor; File system structures therefor of unstructured textual data
- G06F16/36—Creation of semantic tools, e.g. ontology or thesauri
- G06F16/367—Ontology
 
- 
        - G06F17/2705—
 
- 
        - G06F17/2725—
 
- 
        - G06F17/277—
 
- 
        - G06F17/30289—
 
- 
        - G06F17/30297—
 
- 
        - G06F17/30312—
 
- 
        - G06F17/30371—
 
- 
        - G06F17/30734—
 
- 
        - G—PHYSICS
- G06—COMPUTING OR CALCULATING; COUNTING
- G06F—ELECTRIC DIGITAL DATA PROCESSING
- G06F40/00—Handling natural language data
- G06F40/20—Natural language analysis
- G06F40/205—Parsing
 
- 
        - G—PHYSICS
- G06—COMPUTING OR CALCULATING; COUNTING
- G06F—ELECTRIC DIGITAL DATA PROCESSING
- G06F40/00—Handling natural language data
- G06F40/20—Natural language analysis
- G06F40/205—Parsing
- G06F40/211—Syntactic parsing, e.g. based on context-free grammar [CFG] or unification grammars
 
- 
        - G—PHYSICS
- G06—COMPUTING OR CALCULATING; COUNTING
- G06F—ELECTRIC DIGITAL DATA PROCESSING
- G06F40/00—Handling natural language data
- G06F40/20—Natural language analysis
- G06F40/205—Parsing
- G06F40/226—Validation
 
- 
        - G—PHYSICS
- G06—COMPUTING OR CALCULATING; COUNTING
- G06F—ELECTRIC DIGITAL DATA PROCESSING
- G06F40/00—Handling natural language data
- G06F40/20—Natural language analysis
- G06F40/279—Recognition of textual entities
- G06F40/284—Lexical analysis, e.g. tokenisation or collocates
 
Definitions
- the present disclosure generally relates to techniques for creating data in a data store.
- Computer-based database systems such as relational database management systems, typically organize data according to a fixed structure of tables and relationships.
- the structure may be described using an ontology, embodied in a database schema, comprising a data model that is used to represent the structure and reason about objects in the structure.
- An ontology of a database is normally fixed at the time that the database is created. Any change in the ontology represented by the schema is typically extremely disruptive to the database system and requires a database administrator to modify tables or relationships, or create new tables or relationships.
- a method comprises creating and storing an ontology for a data store in response to receiving first user input defining the ontology, wherein the ontology comprises a plurality of data object types and a plurality of object property types; creating one or more parser definitions in response to receiving second user input defining the parser definitions, wherein each of the parser definitions specifies one or more sub-definitions of how to transform first input data into modified input data that is compatible with one of the object property types; storing each of the one or more parser definitions in association with one of the plurality of object property types; wherein the machine-executed operation is at least one of (a) sending said instructions over transmission media, (b) receiving said instructions over transmission media, (c) storing said instructions onto a machine-readable storage medium, and (d) executing the instructions.
- the method further comprises receiving the first input data; determining whether the first input data matches one of the parser sub-definitions; using a matching one of the parser sub-definitions, creating and storing the modified input data; storing the modified input data in a property of the property type that is identified in the matching one of the parser sub-definitions.
- creating and storing one or more parser definitions comprises creating and storing one or more program code modules, wherein each of the code modules comprises computer program code which when executed causes transforming the first input data into the modified input data.
- creating and storing one or more parser definitions comprises creating and storing one or more transformation expressions, wherein each of the transformation expressions comprises one or more syntactic patterns and a property type identifier associated with each of the syntactic patterns.
- creating and storing one or more parser definitions comprises creating and storing one or more transformation expressions, wherein each of the transformation expressions comprises one or more syntactic patterns and a property type identifier associated with each of the syntactic patterns, and the method further comprises receiving the first input data; determining whether the first input data matches one of the syntactic patterns; using a matching one of the syntactic patterns, creating and storing modified input data; storing the modified input data in a property of the property type that is identified by the property type identifier associated with the matching one of the syntactic patterns.
- creating one or more parser definitions comprises creating one or more parser definitions comprising a constraint on what modified input data is acceptable for creation of a property of one of the object property types. In a further feature, creating one or more parser definitions comprises creating one or more parser definitions comprising a default value to substitute for one component of the modified input data.
- the method further comprises receiving the first input data; determining whether the first input data matches successive different ones of the parser sub-definitions until a matching parser sub-definition is identified; using a matching one of the parser sub-definitions, creating and storing the modified input data; storing the modified input data in a property of the property type that is identified in the matching one of the parser sub-definitions.
- a data storage system comprises a data store; an ontology coupled to the data store and comprising a plurality of data object types and a plurality of object property types; a parser coupled to the ontology and configured to receive input data and transform the input data into modified data to store in a property of one of the property types according to one or more parser definitions; wherein each of the object property types comprises one or more of the parser definitions, wherein each of the parser definitions specifies one or more sub-definitions of how to transform first input data into modified input data that is compatible with one of the object property types.
- an apparatus comprises means for creating and storing an ontology for a data store in response to receiving first user input defining the ontology, wherein the ontology comprises a plurality of data object types and a plurality of object property types; means for creating one or more parser definitions in response to receiving second user input defining the parser definitions, wherein each of the parser definitions specifies one or more sub-definitions of how to transform first input data into modified input data that is compatible with one of the object property types; and means for storing each of the one or more parser definitions in association with one of the plurality of object property types.
- a graphical user interface comprises an expression pattern field configured to accept user input specifying a transformation expression pattern that specifies how to transform first input data into modified input data; one or more parser sub-definitions each comprising: a portion of the transformation expression pattern; a combo box configured to accept user input specifying one of a plurality of object property component types of an ontology of a data store; wherein each of the parser sub-definitions specifies how to transform a portion of the first input data into a portion of modified input that can be stored in the specified component of one of the plurality of object property types.
- the one or more parser sub-definitions comprise a constraint on how to transform the portion of the first input data into the portion of modified input data that is compatible with one of the object property types. In yet another feature, the one or more parser sub-definitions comprise a default value to substitute for the modified input data if it is empty.
- FIG. 1 illustrates a system for creating data in a data store using a dynamic ontology
- FIG. 2 illustrates defining a dynamic ontology for use in creating data in a data store
- FIG. 3 illustrates a method of transforming data and creating the data in a data store using a dynamic ontology
- FIG. 4 illustrates an example object type editor
- FIG. 5A illustrates an example parser editor
- FIG. 5B illustrates an example property editing wizard in which multiple parsers have been created for a particular property
- FIG. 6 illustrates a computer system with which an embodiment may be implemented.
- a user of a database system specifies an ontology of the database in terms of object types and property types for properties of the objects. The user further specifies how to parse input data for the database and how to map the parsed data into database elements such as objects or object properties.
- the database is chosen as an example embodiment, other embodiments such as flat files or search indexes could be considered as well.
- FIG. 1 illustrates a system for creating data in a database using a dynamic ontology.
- a parser 102 is coupled to an ontology 106 , which is coupled to a database 108 .
- ontology 106 comprises stored information providing a data model of data stored in database 108 , and the ontology is defined by one or more object types 110 and one or more property types 116 .
- One or more objects 112 in the database 108 may be instantiated based on the object types 110 , and each of the objects has one or more properties 114 A, 114 B that are instantiated based on property types 116 .
- the property types 116 each may comprise one or more components 118 , such as a string, number, etc.
- Property types 116 may be instantiated based on a base type 120 .
- a base type 120 may be “Locations” and a property type 116 may be “Home.”
- a user of the system uses an object type editor 124 to create the object types 110 and define attributes of the object types.
- a user of the system uses a property type editor 126 to create the property types 116 and define attributes of the property types.
- creating a property type 116 using the property type editor 126 involves defining at least one parser definition using a parser editor 122 .
- a parser definition comprises metadata that informs parser 102 how to parse input data 100 to determine whether values in the input data can be assigned to the property type 116 that is associated with the parser definition.
- each parser definition may comprise a regular expression parser 104 A or a code module parser 104 B.
- other kinds of parser definitions may be provided using scripts or other programmatic elements. The elements of a regular expression parser 104 A and a code module parser 104 B are described further in subsequent sections. Once defined, both a regular expression parser 104 A and a code module parser 104 B can provide input to parser 102 to control parsing of input data 100 .
- input data 100 is provided to parser 102 .
- An object-property mapping for the input data 100 enables the parser to determine which object type 110 should receive data from a row of the input data, and which property types 116 should receive data from individual field values in the input data.
- the parser 102 selects one of the parser definitions that is associated with a property type in the input data.
- the parser parses an input data field using the selected parser definition, resulting in creating modified data 103 .
- the modified data 103 is added to the database 108 according to ontology 106 by storing values of the modified data in a property of the specified property type.
- input data 100 having varying format or syntax can be created in database 108 .
- the ontology 106 may be modified at any time using object type editor 124 and property type editor 126 .
- Parser editor 122 enables creating multiple parser definitions that can successfully parse input data 100 having varying format or syntax and determine which property types should be used to transform input data 100 into modified input data 103 .
- FIG. 2 illustrates defining a dynamic ontology for use in creating data in a database.
- steps 202 - 209 of FIG. 2 are first described at a high level, and details of an example implementation follow the high level description.
- step 202 one or more object types are created for a database ontology.
- step 206 one or more property types are created for each object type.
- the attributes of object types or property types of the ontology may be edited or modified at any time.
- step 208 at least one parser definition is created for each property type.
- attributes of a parser definition may be edited or modified at any time.
- each property type is declared to be representative of one or more object types.
- a property type is representative of an object type when the property type is intuitively associated with the object type. For example, a property type of “Social Security Number” may be representative of an object type “Person” but not representative of an object type “Business.”
- each property type has one or more components and a base type.
- a property type may comprise a string, a date, a number, or a composite type consisting of two or more string, date, or number elements.
- property types are extensible and can represent complex data structures. Further, a parser definition can reference a component of a complex property type as a unit or token.
- An example of a property having multiple components is a Name property having a Last Name component and a First Name component.
- An example of raw input data is “Smith, Jane”.
- An example parser definition specifies an association of input data to object property components as follows: ⁇ LAST_NAME ⁇ , ⁇ FIRST_NAME ⁇ Name:Last, Name:First.
- the association ⁇ LAST_NAME ⁇ , ⁇ FIRST_NAME ⁇ is defined in a parser definition using regular expression symbology.
- the association ⁇ LAST_NAME ⁇ , ⁇ FIRST_NAME ⁇ indicates that a last name string followed by a first name string comprises valid input data for a property of type Name.
- parsing the input data using the parser definition results in assigning the value “Smith” to the Name:Last component of the Name property, and the value “Jane” to the Name:First component of the Name property.
- administrative users use an administrative editor to create or edit object types and property types.
- users use the administrative editor to specify parser definitions and to associate regular expressions, code modules or scripts with the parser definitions.
- a user can specify attributes and components of a property type. For example, in one embodiment a user specifies a graphical user interface icon that is associated with the property type and displayed in a user interface for selecting the property type. The user further specifies a parser definition that is associated with the property type and that can parse input data and map the input data to properties corresponding to the property type. The user further specifies a display format for the property type indicating how users will see properties of that property type.
- FIG. 4 illustrates an example object type editor.
- an object type editor panel 402 comprises graphical buttons 404 for selecting add, delete, and edit functions, and one or more rows 406 that identify object types and a summary of selected attributes of the object types.
- Example selected attributes that can be displayed in object editor panel 402 include an object type name 408 (for example, “Business”), a uniform resource identifier (URI) 410 specifying a location of information defining the object type (for example, “com.palantir.object.business”), and a base type 412 of the object type, also expressed in URI format (for example, “com.palantir.object.entity”).
- Each URI also may include a graphical icon 414 .
- a user interacts with a computer to perform the following steps to define an object type.
- the new object type is Vehicle.
- the user selects the “Add Object Type” button 404 and the computer generates and displays a panel that prompts the user to enter values for a new object type.
- the user selects a base object type of Entity, which may comprise any person, place or thing.
- the user assigns a graphical icon to the Vehicle object type.
- the user assigns a display name of “Vehicle” to the object type.
- a user interacts with the computer to define a property type in a similar manner.
- the user specifies a name for the property type, a display name, and an icon.
- the user may specify one or more validators for a property type.
- Each validator may comprise a regular expression that input data modified by a parser must match to constitute valid data for that property type.
- each validator is applied to input data before a process can store the modified input data in an object property of the associated property type.
- Validators are applied after parsing and before input data is allowed to be stored in an object property.
- validators may comprise regular expressions, a set of fixed values, or a code module.
- a property type that is a number may have a validator comprising a regular expression that matches digits 0 to 9.
- a property type that is a US state may have a validator that comprises the set ⁇ AK, AL, CA . . . VA ⁇ of valid two-letter postal abbreviations for states.
- Validator sets may be extendible to allow a user to add further values.
- a property type may have component elements, and each component element may have a different validator.
- a property type of “Address” may comprise as components “City”, “State”, and “ZIP”, each of which may have a different validator.
- defining a property type includes identifying one or more associated words for the property type.
- the associated words support search functions in large database systems. For example, a property type of “Address” may have an associated word of “home” so that a search in the system for “home” properties will yield “Address” as one result.
- defining a property type includes identifying a display formatter for the property type.
- a display formatter specifies how to print or display a property type value.
- the parser definitions each include a regular expression that matches valid input, and the parser uses a regular expression processing module.
- a regular expression processing module For example, conventional Java language processors typically have regular expression processing modules built in.
- parser definitions comprising regular expressions may be chained together.
- one or more of the parser definitions each include a code module that contains logic for parsing input data and determining whether the input data matches a specified syntax or data model. The code module may be written in Java, JavaScript, or any other suitable source language.
- parser definitions and sub-definitions there may be any number of parser definitions and sub-definitions.
- the number of parser definitions is unimportant because the input data is applied successively to each parser definition until a match occurs.
- the input data is mapped using the parser sub definitions to one or more components of an instance of an object property.
- input data can vary syntactically from a desired syntax but correct data values are mapped into correct object property values in a database.
- creating a parser definition for a property type at step 208 may comprise selecting a parser type such as a regular expression, code module, or other parser type.
- a parser type such as a regular expression, code module, or other parser type.
- code module a parser type
- a user specifies the name of a particular code module, script, or other functional element that can perform parsing for the associated property type.
- defining a property type includes creating a definition of a parser for the property type using a parser editor.
- FIG. 5A illustrates an example parser editor user interface screen display.
- screen display 502 comprises a Parser Type combo box 504 that can receive a user selection of a parser type, such as “Regular Expression” or “Code Module.”
- Screen display 502 further comprises a Name text entry box 506 that can receive a user-specified name for the parser definition.
- step 214 regular expression text is specified.
- screen display 502 comprises an Expression Pattern text box 508 that can receive a user entry of regular expression pattern text.
- step 216 a property type component and a matching sub-definition of regular expression text is specified.
- screen display 502 further comprises one or more property type component mappings 510 .
- Each property type component mapping associates a sub-definition of the regular expression pattern text with the property type component that is shown in a combo box 512 .
- a user specifies a property type component by selecting a property type component using combo box 512 for an associated sub-definition 513 .
- specifying a property type component and sub-definition of regular expression text may be repeated for all other property type components of a particular property type.
- six (6) property type component mappings 510 have been created for different property types (ADDRESS1, ADDRESS2, ADDRESS3, CITY, STATE, ZIP).
- a user may specify one or more constraints, default values, and/or other attributes of a parser definition.
- the user also may specify that a match to a particular property type component is not required by checking a “Not Required” check box 514 .
- Screen display 502 may further comprise a Default Value text box 514 that can receive user input for a default value for the property type component. If a Default Value is specified, then the associated property type receives that value if no match occurs for associated grouping of the regular expression. In alternative embodiments, other constraints may be specified.
- the parser definition is stored in association with a property type. For example, selecting the SAVE button 520 of FIG. 5A causes storing a parser definition based on the values entered in screen display 502 . Parser definitions may be stored in database 108 .
- FIG. 2 For purposes of illustrating a clear example, the approach of FIG. 2 has been described with reference to FIG. 5A . However, the approach of FIG. 2 may be implemented using other mechanisms for creating and specifying the values and elements identified in FIG. 2 , and the particular GUI of FIG. 5A is not required.
- FIG. 3 illustrates a method of transforming data and creating the data in a database using a dynamic ontology.
- the approach of FIG. 3 is described herein with reference to FIG. 1 .
- the approach of FIG. 3 may be implemented using other mechanisms for performing the functional steps of FIG. 3 , and the particular system of FIG. 1 is not required.
- step 302 input data is received.
- an input data file is received.
- the input data file may comprise a comma-separated value (CSV) file, a spreadsheet, XML or other input data file format.
- Input data 100 of FIG. 1 may represent such file formats or any other form of input data.
- an object type associated with input data rows of the input data is identified, and one or more property types associated with input data fields of the input data are identified.
- the object-property mapping 101 of FIG. 1 specifies that input data 100 comprises rows corresponding to object type PERSON and fields corresponding to property type components LAST_NAME, FIRST_NAME of property type NAME.
- the object-property mapping 101 may be integrated into input data 100 or may be stored as metadata in association with a data input tool.
- step 306 a row of data is read from the input data, and one or more field values are identified based on delimiters or other field identifiers in the input data.
- a set of parser definitions associated with the property type of a particular input data field is selected. For example, metadata stored as part of creating a property type specifies a set of parser definitions, as previously described in connection with FIG. 5A .
- step 310 the next parser definition is applied to an input data field value.
- data fields are read from each row of the file and matched to each parser that has been defined for the corresponding property types.
- the mapping indicates that an input data CSV file comprises (Last Name, First Name) values for Name properties of Person objects.
- Data fields are read from the input data CSV file and compared to each of the parsers that has been defined for the Name property type given the First Name field and Last Name field.
- the parser transforms the input data pair of (,Last Name, First Name) into modified input data to be stored in an instantiation of a Name property.
- a property instance is created, and the input data field value is stored in a property of the property type associated with the matching sub-definition of the parser definition. For example, referring to FIG. 5A , assume that the input data matches the regular expression 508 for an ADDRESS value.
- the mapping 510 specifies how to store the data matching each grouping of the regular expression into a component of the ADDRESS property.
- an instance of an ADDRESS property is created in computer memory and the matching modified input data value is stored in each component of the property instance.
- step 312 If no match occurs at step 312 , then control transfers to step 314 to test whether other parser definitions match the same input data value.
- FIG. 5B illustrates an example property editing wizard in which multiple parsers have been created for a particular property, and through the loop shown in FIG. 3 , each of the multiple parsers can be used in matching input data. If no match occurs to the given parser definition, then any other parser definitions for that property type are matched until either no match occurs, or no other parser definitions are available.
- step 314 If a grouping is empty, then the component is filled by the default value for that component, if it exists. If no other parser definitions are available, then control transfers from step 314 to step 316 , at which point an error is raised or the property is discarded
- step 320 the preceding steps are repeated for all other values and rows in the input data until the process has transformed all the input data into properties in memory.
- an object of the correct object type is instantiated.
- the object-property mapping 101 may specify an object type for particular input data, and that type of object is instantiated.
- the newly created object is associated in memory with the properties that are already in memory.
- the resulting object is stored in the database in step 324 .
- Steps in the preceding process may be organized in a pipeline.
- a user can self-define a database ontology and use automated, machine-based techniques to transform input data according to user-defined parsers and store the transformed data in the database according to the ontology.
- the approach provides efficient movement of data into a database according to an ontology.
- the input data has improved intelligibility after transformation because the data is stored in a canonical ontology.
- the approach is flexible and adaptable, because the user can modify the ontology at any time and is not tied to a fixed ontology.
- the user also can define multiple parsers to result in semantic matches to input data even when the syntax of the input data is variable.
- FIG. 6 is a block diagram that illustrates a computer system 600 upon which an embodiment of the invention may be implemented.
- Computer system 600 includes a bus 602 or other communication mechanism for communicating information, and a processor 604 coupled with bus 602 for processing information.
- Computer system 600 also includes a main memory 606 , such as a random access memory (RAM) or other dynamic storage device, coupled to bus 602 for storing information and instructions to be executed by processor 604 .
- Main memory 606 also may be used for storing temporary variables or other intermediate information during execution of instructions to be executed by processor 604 .
- Computer system 600 further includes a read only memory (ROM) 608 or other static storage device coupled to bus 602 for storing static information and instructions for processor 604 .
- ROM read only memory
- a storage device 610 such as a magnetic disk or optical disk, is provided and coupled to bus 602 for storing information and instructions.
- Computer system 600 may be coupled via bus 602 to a display 612 , such as a cathode ray tube (CRT), for displaying information to a computer user.
- a display 612 such as a cathode ray tube (CRT)
- An input device 614 is coupled to bus 602 for communicating information and command selections to processor 604 .
- cursor control 616 is Another type of user input device
- cursor control 616 such as a mouse, a trackball, or cursor direction keys for communicating direction information and command selections to processor 604 and for controlling cursor movement on display 612 .
- This input device typically has two degrees of freedom in two axes, a first axis (e.g., x) and a second axis (e.g., y), that allows the device to specify positions in a plane.
- the invention is related to the use of computer system 600 for implementing the techniques described herein. According to one embodiment of the invention, those techniques are performed by computer system 600 in response to processor 604 executing one or more sequences of one or more instructions contained in main memory 606 . Such instructions may be read into main memory 606 from another machine-readable medium, such as storage device 610 . Execution of the sequences of instructions contained in main memory 606 causes processor 604 to perform the process steps described herein. In alternative embodiments, hard-wired circuitry may be used in place of or in combination with software instructions to implement the invention. Thus, embodiments of the invention are not limited to any specific combination of hardware circuitry and software.
- machine-readable medium refers to any medium that participates in providing data that causes a machine to operation in a specific fashion.
- various machine-readable media are involved, for example, in providing instructions to processor 604 for execution.
- Such a medium may take many forms, including but not limited to, non-volatile media, volatile media, and transmission media.
- Non-volatile media includes, for example, optical or magnetic disks, such as storage device 610 .
- Volatile media includes dynamic memory, such as main memory 606 .
- Transmission media includes coaxial cables, copper wire and fiber optics, including the wires that comprise bus 602 .
- Transmission media can also take the form of acoustic or light waves, such as those generated during radio wave and infrared data communications. All such media must be tangible to enable the instructions carried by the media to be detected by a physical mechanism that reads the instructions into a machine.
- Machine-readable media include, for example, a floppy disk, a flexible disk, hard disk, magnetic tape, or any other magnetic medium, a CD-ROM, any other optical medium, punch cards, paper tape, any other physical medium with patterns of holes, a RAM, a PROM, and EPROM, a FLASH-EPROM, any other memory chip or cartridge, a carrier wave as described hereinafter, or any other medium from which a computer can read.
- Various forms of machine-readable media may be involved in carrying one or more sequences of one or more instructions to processor 604 for execution.
- the instructions may initially be carried on a magnetic disk of a remote computer.
- the remote computer can load the instructions into its dynamic memory and send the instructions over a telephone line using a modem.
- a modem local to computer system 600 can receive the data on the telephone line and use an infrared transmitter to convert the data to an infrared signal.
- An infrared detector can receive the data carried in the infrared signal and appropriate circuitry can place the data on bus 602 .
- Bus 602 carries the data to main memory 606 , from which processor 604 retrieves and executes the instructions.
- the instructions received by main memory 606 may optionally be stored on storage device 610 either before or after execution by processor 604 .
- Computer system 600 also includes a communication interface 618 coupled to bus 602 .
- Communication interface 618 provides a two-way data communication coupling to a network link 620 that is connected to a local network 622 .
- communication interface 618 may be an integrated services digital network (ISDN) card or a modem to provide a data communication connection to a corresponding type of telephone line.
- ISDN integrated services digital network
- communication interface 618 may be a local area network (LAN) card to provide a data communication connection to a compatible LAN.
- LAN local area network
- Wireless links may also be implemented.
- communication interface 618 sends and receives electrical, electromagnetic or optical signals that carry digital data streams representing various types of information.
- Network link 620 typically provides data communication through one or more networks to other data devices.
- network link 620 may provide a connection through local network 622 to a host computer 624 or to data equipment operated by an Internet Service Provider (ISP) 626 .
- ISP 626 in turn provides data communication services through the worldwide packet data communication network now commonly referred to as the “Internet” 628 .
- Internet 628 uses electrical, electromagnetic or optical signals that carry digital data streams.
- the signals through the various networks and the signals on network link 620 and through communication interface 618 which carry the digital data to and from computer system 600 , are exemplary forms of carrier waves transporting the information.
- Computer system 600 can send messages and receive data, including program code, through the network(s), network link 620 and communication interface 618 .
- a server 630 might transmit a requested code for an application program through Internet 628 , ISP 626 , local network 622 and communication interface 618 .
- the received code may be executed by processor 604 as it is received, and/or stored in storage device 610 , or other non-volatile storage for later execution. In this manner, computer system 600 may obtain application code in the form of a carrier wave.
Landscapes
- Engineering & Computer Science (AREA)
- Theoretical Computer Science (AREA)
- Physics & Mathematics (AREA)
- General Engineering & Computer Science (AREA)
- General Physics & Mathematics (AREA)
- Databases & Information Systems (AREA)
- Data Mining & Analysis (AREA)
- Computational Linguistics (AREA)
- Audiology, Speech & Language Pathology (AREA)
- General Health & Medical Sciences (AREA)
- Artificial Intelligence (AREA)
- Health & Medical Sciences (AREA)
- Software Systems (AREA)
- Life Sciences & Earth Sciences (AREA)
- Animal Behavior & Ethology (AREA)
- Computer Security & Cryptography (AREA)
- User Interface Of Digital Computer (AREA)
- Information Retrieval, Db Structures And Fs Structures Therefor (AREA)
- Stored Programmes (AREA)
- Input From Keyboards Or The Like (AREA)
- Machine Translation (AREA)
- Document Processing Apparatus (AREA)
Abstract
Description
Claims (20)
Priority Applications (4)
| Application Number | Priority Date | Filing Date | Title | 
|---|---|---|---|
| US14/954,680 US9589014B2 (en) | 2006-11-20 | 2015-11-30 | Creating data in a data store using a dynamic ontology | 
| US15/448,491 US10872067B2 (en) | 2006-11-20 | 2017-03-02 | Creating data in a data store using a dynamic ontology | 
| US17/123,019 US11714792B2 (en) | 2006-11-20 | 2020-12-15 | Creating data in a data store using a dynamic ontology | 
| US18/336,876 US12386803B2 (en) | 2006-11-20 | 2023-06-16 | Creating data in a data store using a dynamic ontology | 
Applications Claiming Priority (5)
| Application Number | Priority Date | Filing Date | Title | 
|---|---|---|---|
| US11/602,626 US7962495B2 (en) | 2006-11-20 | 2006-11-20 | Creating data in a data store using a dynamic ontology | 
| US13/106,636 US8489623B2 (en) | 2006-11-20 | 2011-05-12 | Creating data in a data store using a dynamic ontology | 
| US13/916,447 US8856153B2 (en) | 2006-11-20 | 2013-06-12 | Creating data in a data store using a dynamic ontology | 
| US14/508,696 US9201920B2 (en) | 2006-11-20 | 2014-10-07 | Creating data in a data store using a dynamic ontology | 
| US14/954,680 US9589014B2 (en) | 2006-11-20 | 2015-11-30 | Creating data in a data store using a dynamic ontology | 
Related Parent Applications (1)
| Application Number | Title | Priority Date | Filing Date | 
|---|---|---|---|
| US14/508,696 Continuation US9201920B2 (en) | 2006-11-20 | 2014-10-07 | Creating data in a data store using a dynamic ontology | 
Related Child Applications (1)
| Application Number | Title | Priority Date | Filing Date | 
|---|---|---|---|
| US15/448,491 Continuation US10872067B2 (en) | 2006-11-20 | 2017-03-02 | Creating data in a data store using a dynamic ontology | 
Publications (2)
| Publication Number | Publication Date | 
|---|---|
| US20160154845A1 US20160154845A1 (en) | 2016-06-02 | 
| US9589014B2 true US9589014B2 (en) | 2017-03-07 | 
Family
ID=39430552
Family Applications (8)
| Application Number | Title | Priority Date | Filing Date | 
|---|---|---|---|
| US11/602,626 Active 2030-04-14 US7962495B2 (en) | 2006-11-20 | 2006-11-20 | Creating data in a data store using a dynamic ontology | 
| US13/106,636 Active US8489623B2 (en) | 2006-11-20 | 2011-05-12 | Creating data in a data store using a dynamic ontology | 
| US13/916,447 Active US8856153B2 (en) | 2006-11-20 | 2013-06-12 | Creating data in a data store using a dynamic ontology | 
| US14/508,696 Active US9201920B2 (en) | 2006-11-20 | 2014-10-07 | Creating data in a data store using a dynamic ontology | 
| US14/954,680 Active US9589014B2 (en) | 2006-11-20 | 2015-11-30 | Creating data in a data store using a dynamic ontology | 
| US15/448,491 Active 2028-03-01 US10872067B2 (en) | 2006-11-20 | 2017-03-02 | Creating data in a data store using a dynamic ontology | 
| US17/123,019 Active 2027-04-23 US11714792B2 (en) | 2006-11-20 | 2020-12-15 | Creating data in a data store using a dynamic ontology | 
| US18/336,876 Active 2027-06-16 US12386803B2 (en) | 2006-11-20 | 2023-06-16 | Creating data in a data store using a dynamic ontology | 
Family Applications Before (4)
| Application Number | Title | Priority Date | Filing Date | 
|---|---|---|---|
| US11/602,626 Active 2030-04-14 US7962495B2 (en) | 2006-11-20 | 2006-11-20 | Creating data in a data store using a dynamic ontology | 
| US13/106,636 Active US8489623B2 (en) | 2006-11-20 | 2011-05-12 | Creating data in a data store using a dynamic ontology | 
| US13/916,447 Active US8856153B2 (en) | 2006-11-20 | 2013-06-12 | Creating data in a data store using a dynamic ontology | 
| US14/508,696 Active US9201920B2 (en) | 2006-11-20 | 2014-10-07 | Creating data in a data store using a dynamic ontology | 
Family Applications After (3)
| Application Number | Title | Priority Date | Filing Date | 
|---|---|---|---|
| US15/448,491 Active 2028-03-01 US10872067B2 (en) | 2006-11-20 | 2017-03-02 | Creating data in a data store using a dynamic ontology | 
| US17/123,019 Active 2027-04-23 US11714792B2 (en) | 2006-11-20 | 2020-12-15 | Creating data in a data store using a dynamic ontology | 
| US18/336,876 Active 2027-06-16 US12386803B2 (en) | 2006-11-20 | 2023-06-16 | Creating data in a data store using a dynamic ontology | 
Country Status (14)
| Country | Link | 
|---|---|
| US (8) | US7962495B2 (en) | 
| EP (3) | EP3462304B1 (en) | 
| AU (1) | AU2007323689B2 (en) | 
| CA (1) | CA2666364C (en) | 
| DK (1) | DK2084597T3 (en) | 
| ES (1) | ES2702611T3 (en) | 
| HU (1) | HUE041455T2 (en) | 
| IL (1) | IL198253A (en) | 
| LT (1) | LT2084597T (en) | 
| PL (1) | PL2084597T3 (en) | 
| PT (1) | PT2084597T (en) | 
| SI (1) | SI2084597T1 (en) | 
| TR (1) | TR201900500T4 (en) | 
| WO (1) | WO2008064207A2 (en) | 
Cited By (3)
| Publication number | Priority date | Publication date | Assignee | Title | 
|---|---|---|---|---|
| US10248722B2 (en) | 2016-02-22 | 2019-04-02 | Palantir Technologies Inc. | Multi-language support for dynamic ontology | 
| US10803106B1 (en) | 2015-02-24 | 2020-10-13 | Palantir Technologies Inc. | System with methodology for dynamic modular ontology | 
| US10872067B2 (en) | 2006-11-20 | 2020-12-22 | Palantir Technologies, Inc. | Creating data in a data store using a dynamic ontology | 
Families Citing this family (289)
| Publication number | Priority date | Publication date | Assignee | Title | 
|---|---|---|---|---|
| US8515912B2 (en) | 2010-07-15 | 2013-08-20 | Palantir Technologies, Inc. | Sharing and deconflicting data changes in a multimaster database system | 
| US8688749B1 (en) | 2011-03-31 | 2014-04-01 | Palantir Technologies, Inc. | Cross-ontology multi-master replication | 
| US7826657B2 (en) * | 2006-12-11 | 2010-11-02 | Yahoo! Inc. | Automatically generating a content-based quality metric for digital images | 
| US20080159383A1 (en) * | 2006-12-27 | 2008-07-03 | Yahoo! Inc. | Tagboard for video tagging | 
| US8930331B2 (en) | 2007-02-21 | 2015-01-06 | Palantir Technologies | Providing unique views of data based on changes or rules | 
| US8554719B2 (en) | 2007-10-18 | 2013-10-08 | Palantir Technologies, Inc. | Resolving database entity information | 
| US20100023549A1 (en) * | 2008-07-22 | 2010-01-28 | Electronics And Telecommunications Research Institute | Method and apparatus for social tagging using property field of ontology object | 
| US8429194B2 (en) | 2008-09-15 | 2013-04-23 | Palantir Technologies, Inc. | Document-based workflows | 
| US8103962B2 (en) * | 2008-11-04 | 2012-01-24 | Brigham Young University | Form-based ontology creation and information harvesting | 
| US9223814B2 (en) * | 2008-11-20 | 2015-12-29 | Microsoft Technology Licensing, Llc | Scalable selection management | 
| US8676808B2 (en) | 2009-07-09 | 2014-03-18 | Dillon Software Services, Llc | Data store interface that facilitates distribution of application functionality across a multi-tier client-server architecture | 
| US9104695B1 (en) | 2009-07-27 | 2015-08-11 | Palantir Technologies, Inc. | Geotagging structured data | 
| US20140289184A1 (en) * | 2009-09-09 | 2014-09-25 | Sanjeev Kumar Biswas | License structure representation for license management | 
| US9507848B1 (en) * | 2009-09-25 | 2016-11-29 | Vmware, Inc. | Indexing and querying semi-structured data | 
| US8694615B2 (en) * | 2009-11-05 | 2014-04-08 | Red Hat, Inc. | Providing identifying information for computers on a network | 
| US20110161069A1 (en) * | 2009-12-30 | 2011-06-30 | Aptus Technologies, Inc. | Method, computer program product and apparatus for providing a threat detection system | 
| US8364642B1 (en) | 2010-07-07 | 2013-01-29 | Palantir Technologies, Inc. | Managing disconnected investigations | 
| CN101901269B (en) * | 2010-08-04 | 2012-05-23 | 国电南瑞科技股份有限公司 | Real-time library foreign key reference display method | 
| US9547693B1 (en) | 2011-06-23 | 2017-01-17 | Palantir Technologies Inc. | Periodic database search manager for multiple data sources | 
| US8799240B2 (en) | 2011-06-23 | 2014-08-05 | Palantir Technologies, Inc. | System and method for investigating large amounts of data | 
| US9092482B2 (en) | 2013-03-14 | 2015-07-28 | Palantir Technologies, Inc. | Fair scheduling for mixed-query loads | 
| US9280532B2 (en) | 2011-08-02 | 2016-03-08 | Palantir Technologies, Inc. | System and method for accessing rich objects via spreadsheets | 
| US8732574B2 (en) | 2011-08-25 | 2014-05-20 | Palantir Technologies, Inc. | System and method for parameterizing documents for automatic workflow generation | 
| US8504542B2 (en) | 2011-09-02 | 2013-08-06 | Palantir Technologies, Inc. | Multi-row transactions | 
| US8560494B1 (en) | 2011-09-30 | 2013-10-15 | Palantir Technologies, Inc. | Visual data importer | 
| US8782004B2 (en) | 2012-01-23 | 2014-07-15 | Palantir Technologies, Inc. | Cross-ACL multi-master replication | 
| US9710763B2 (en) * | 2012-06-27 | 2017-07-18 | Sheldon O. Linker | Method and system for robot understanding, knowledge, conversation, volition, planning, and actuation | 
| US20140059296A1 (en) * | 2012-08-27 | 2014-02-27 | Synchronoss Technologies, Inc. | Storage technology agnostic system for persisting software instantiated objects | 
| US9348677B2 (en) | 2012-10-22 | 2016-05-24 | Palantir Technologies Inc. | System and method for batch evaluation programs | 
| US9081975B2 (en) | 2012-10-22 | 2015-07-14 | Palantir Technologies, Inc. | Sharing information between nexuses that use different classification schemes for information access control | 
| US9501761B2 (en) | 2012-11-05 | 2016-11-22 | Palantir Technologies, Inc. | System and method for sharing investigation results | 
| US9501507B1 (en) | 2012-12-27 | 2016-11-22 | Palantir Technologies Inc. | Geo-temporal indexing and searching | 
| GB201300255D0 (en) * | 2013-01-08 | 2013-02-20 | Ibm | Object naming | 
| US9380431B1 (en) | 2013-01-31 | 2016-06-28 | Palantir Technologies, Inc. | Use of teams in a mobile application | 
| US10140664B2 (en) | 2013-03-14 | 2018-11-27 | Palantir Technologies Inc. | Resolving similar entities from a transaction database | 
| US10037314B2 (en) | 2013-03-14 | 2018-07-31 | Palantir Technologies, Inc. | Mobile reports | 
| US8937619B2 (en) | 2013-03-15 | 2015-01-20 | Palantir Technologies Inc. | Generating an object time series from data objects | 
| US8855999B1 (en) | 2013-03-15 | 2014-10-07 | Palantir Technologies Inc. | Method and system for generating a parser and parsing complex data | 
| US10275778B1 (en) | 2013-03-15 | 2019-04-30 | Palantir Technologies Inc. | Systems and user interfaces for dynamic and interactive investigation based on automatic malfeasance clustering of related data in various data structures | 
| US8788405B1 (en) | 2013-03-15 | 2014-07-22 | Palantir Technologies, Inc. | Generating data clusters with customizable analysis strategies | 
| US8917274B2 (en) | 2013-03-15 | 2014-12-23 | Palantir Technologies Inc. | Event matrix based on integrated data | 
| US9898167B2 (en) | 2013-03-15 | 2018-02-20 | Palantir Technologies Inc. | Systems and methods for providing a tagging interface for external content | 
| US8909656B2 (en) | 2013-03-15 | 2014-12-09 | Palantir Technologies Inc. | Filter chains with associated multipath views for exploring large data sets | 
| US8903717B2 (en) | 2013-03-15 | 2014-12-02 | Palantir Technologies Inc. | Method and system for generating a parser and parsing complex data | 
| US8930897B2 (en) * | 2013-03-15 | 2015-01-06 | Palantir Technologies Inc. | Data integration tool | 
| US8924388B2 (en) | 2013-03-15 | 2014-12-30 | Palantir Technologies Inc. | Computer-implemented systems and methods for comparing and associating objects | 
| GB2513007A (en) | 2013-03-15 | 2014-10-15 | Palantir Technologies Inc | Transformation of data items from data sources using a transformation script | 
| US9740369B2 (en) | 2013-03-15 | 2017-08-22 | Palantir Technologies Inc. | Systems and methods for providing a tagging interface for external content | 
| US9501202B2 (en) | 2013-03-15 | 2016-11-22 | Palantir Technologies, Inc. | Computer graphical user interface with genomic workflow | 
| US8868486B2 (en) | 2013-03-15 | 2014-10-21 | Palantir Technologies Inc. | Time-sensitive cube | 
| US9965937B2 (en) | 2013-03-15 | 2018-05-08 | Palantir Technologies Inc. | External malware data item clustering and analysis | 
| US9818211B1 (en) * | 2013-04-25 | 2017-11-14 | Domo, Inc. | Automated combination of multiple data visualizations | 
| US8799799B1 (en) | 2013-05-07 | 2014-08-05 | Palantir Technologies Inc. | Interactive geospatial map | 
| US8886601B1 (en) | 2013-06-20 | 2014-11-11 | Palantir Technologies, Inc. | System and method for incrementally replicating investigative analysis data | 
| US8601326B1 (en) | 2013-07-05 | 2013-12-03 | Palantir Technologies, Inc. | Data quality monitors | 
| US9223773B2 (en) | 2013-08-08 | 2015-12-29 | Palatir Technologies Inc. | Template system for custom document generation | 
| US9335897B2 (en) | 2013-08-08 | 2016-05-10 | Palantir Technologies Inc. | Long click display of a context menu | 
| US8713467B1 (en) | 2013-08-09 | 2014-04-29 | Palantir Technologies, Inc. | Context-sensitive views | 
| US9335976B1 (en) * | 2013-09-10 | 2016-05-10 | Google Inc. | Tracking property representations in modified computational objects | 
| US9250874B1 (en) * | 2013-09-11 | 2016-02-02 | Google Inc. | Sharing property descriptor information between object maps | 
| US9785317B2 (en) | 2013-09-24 | 2017-10-10 | Palantir Technologies Inc. | Presentation and analysis of user interaction data | 
| US8938686B1 (en) | 2013-10-03 | 2015-01-20 | Palantir Technologies Inc. | Systems and methods for analyzing performance of an entity | 
| US8812960B1 (en) | 2013-10-07 | 2014-08-19 | Palantir Technologies Inc. | Cohort-based presentation of user interaction data | 
| US8924872B1 (en) | 2013-10-18 | 2014-12-30 | Palantir Technologies Inc. | Overview user interface of emergency call data of a law enforcement agency | 
| US9116975B2 (en) | 2013-10-18 | 2015-08-25 | Palantir Technologies Inc. | Systems and user interfaces for dynamic and interactive simultaneous querying of multiple data stores | 
| US9021384B1 (en) | 2013-11-04 | 2015-04-28 | Palantir Technologies Inc. | Interactive vehicle information map | 
| US9569070B1 (en) | 2013-11-11 | 2017-02-14 | Palantir Technologies, Inc. | Assisting in deconflicting concurrency conflicts | 
| US8868537B1 (en) | 2013-11-11 | 2014-10-21 | Palantir Technologies, Inc. | Simple web search | 
| US9105000B1 (en) | 2013-12-10 | 2015-08-11 | Palantir Technologies Inc. | Aggregating data from a plurality of data sources | 
| EP2884440A1 (en) | 2013-12-16 | 2015-06-17 | Palantir Technologies, Inc. | Methods and systems for analyzing entity performance | 
| US10025834B2 (en) | 2013-12-16 | 2018-07-17 | Palantir Technologies Inc. | Methods and systems for analyzing entity performance | 
| US10474747B2 (en) | 2013-12-16 | 2019-11-12 | International Business Machines Corporation | Adjusting time dependent terminology in a question and answer system | 
| US10579647B1 (en) | 2013-12-16 | 2020-03-03 | Palantir Technologies Inc. | Methods and systems for analyzing entity performance | 
| US9552615B2 (en) | 2013-12-20 | 2017-01-24 | Palantir Technologies Inc. | Automated database analysis to detect malfeasance | 
| US10356032B2 (en) | 2013-12-26 | 2019-07-16 | Palantir Technologies Inc. | System and method for detecting confidential information emails | 
| US9338013B2 (en) | 2013-12-30 | 2016-05-10 | Palantir Technologies Inc. | Verifiable redactable audit log | 
| US9043696B1 (en) | 2014-01-03 | 2015-05-26 | Palantir Technologies Inc. | Systems and methods for visual definition of data associations | 
| US8832832B1 (en) | 2014-01-03 | 2014-09-09 | Palantir Technologies Inc. | IP reputation | 
| US9009827B1 (en) | 2014-02-20 | 2015-04-14 | Palantir Technologies Inc. | Security sharing system | 
| US9483162B2 (en) * | 2014-02-20 | 2016-11-01 | Palantir Technologies Inc. | Relationship visualizations | 
| US20150235334A1 (en) | 2014-02-20 | 2015-08-20 | Palantir Technologies Inc. | Healthcare fraud sharing system | 
| US9727376B1 (en) | 2014-03-04 | 2017-08-08 | Palantir Technologies, Inc. | Mobile tasks | 
| US8924429B1 (en) | 2014-03-18 | 2014-12-30 | Palantir Technologies Inc. | Determining and extracting changed data from a data source | 
| US9836580B2 (en) | 2014-03-21 | 2017-12-05 | Palantir Technologies Inc. | Provider portal | 
| US9857958B2 (en) | 2014-04-28 | 2018-01-02 | Palantir Technologies Inc. | Systems and user interfaces for dynamic and interactive access of, investigation of, and analysis of data objects stored in one or more databases | 
| US9009171B1 (en) | 2014-05-02 | 2015-04-14 | Palantir Technologies Inc. | Systems and methods for active column filtering | 
| US9619557B2 (en) | 2014-06-30 | 2017-04-11 | Palantir Technologies, Inc. | Systems and methods for key phrase characterization of documents | 
| US9535974B1 (en) | 2014-06-30 | 2017-01-03 | Palantir Technologies Inc. | Systems and methods for identifying key phrase clusters within documents | 
| US9785773B2 (en) | 2014-07-03 | 2017-10-10 | Palantir Technologies Inc. | Malware data item analysis | 
| US9021260B1 (en) | 2014-07-03 | 2015-04-28 | Palantir Technologies Inc. | Malware data item analysis | 
| US9256664B2 (en) | 2014-07-03 | 2016-02-09 | Palantir Technologies Inc. | System and method for news events detection and visualization | 
| US9202249B1 (en) | 2014-07-03 | 2015-12-01 | Palantir Technologies Inc. | Data item clustering and analysis | 
| US10572496B1 (en) | 2014-07-03 | 2020-02-25 | Palantir Technologies Inc. | Distributed workflow system and database with access controls for city resiliency | 
| US9419992B2 (en) | 2014-08-13 | 2016-08-16 | Palantir Technologies Inc. | Unwanted tunneling alert system | 
| US9454281B2 (en) | 2014-09-03 | 2016-09-27 | Palantir Technologies Inc. | System for providing dynamic linked panels in user interface | 
| US9767172B2 (en) | 2014-10-03 | 2017-09-19 | Palantir Technologies Inc. | Data aggregation and analysis system | 
| US9501851B2 (en) | 2014-10-03 | 2016-11-22 | Palantir Technologies Inc. | Time-series analysis system | 
| US9785328B2 (en) | 2014-10-06 | 2017-10-10 | Palantir Technologies Inc. | Presentation of multivariate data on a graphical user interface of a computing system | 
| US9984133B2 (en) | 2014-10-16 | 2018-05-29 | Palantir Technologies Inc. | Schematic and database linking system | 
| US9229952B1 (en) | 2014-11-05 | 2016-01-05 | Palantir Technologies, Inc. | History preserving data pipeline system and method | 
| US9043894B1 (en) | 2014-11-06 | 2015-05-26 | Palantir Technologies Inc. | Malicious software detection in a computing system | 
| US9483546B2 (en) | 2014-12-15 | 2016-11-01 | Palantir Technologies Inc. | System and method for associating related records to common entities across multiple lists | 
| US9348920B1 (en) | 2014-12-22 | 2016-05-24 | Palantir Technologies Inc. | Concept indexing among database of documents using machine learning techniques | 
| US9367872B1 (en) | 2014-12-22 | 2016-06-14 | Palantir Technologies Inc. | Systems and user interfaces for dynamic and interactive investigation of bad actor behavior based on automatic clustering of related data in various data structures | 
| US10552994B2 (en) | 2014-12-22 | 2020-02-04 | Palantir Technologies Inc. | Systems and interactive user interfaces for dynamic retrieval, analysis, and triage of data items | 
| US10362133B1 (en) | 2014-12-22 | 2019-07-23 | Palantir Technologies Inc. | Communication data processing architecture | 
| US10452651B1 (en) | 2014-12-23 | 2019-10-22 | Palantir Technologies Inc. | Searching charts | 
| US9817563B1 (en) | 2014-12-29 | 2017-11-14 | Palantir Technologies Inc. | System and method of generating data points from one or more data stores of data items for chart creation and manipulation | 
| US9467455B2 (en) | 2014-12-29 | 2016-10-11 | Palantir Technologies Inc. | Systems for network risk assessment including processing of user access rights associated with a network of devices | 
| US9335911B1 (en) | 2014-12-29 | 2016-05-10 | Palantir Technologies Inc. | Interactive user interface for dynamic data analysis exploration and query processing | 
| US9648036B2 (en) | 2014-12-29 | 2017-05-09 | Palantir Technologies Inc. | Systems for network risk assessment including processing of user access rights associated with a network of devices | 
| US12443336B2 (en) | 2014-12-29 | 2025-10-14 | Palantir Technologies Inc. | Interactive user interface for dynamically updating data and data analysis and query processing | 
| US9870205B1 (en) | 2014-12-29 | 2018-01-16 | Palantir Technologies Inc. | Storing logical units of program code generated using a dynamic programming notebook user interface | 
| US10372879B2 (en) | 2014-12-31 | 2019-08-06 | Palantir Technologies Inc. | Medical claims lead summary report generation | 
| US11302426B1 (en) | 2015-01-02 | 2022-04-12 | Palantir Technologies Inc. | Unified data interface and system | 
| US10387834B2 (en) * | 2015-01-21 | 2019-08-20 | Palantir Technologies Inc. | Systems and methods for accessing and storing snapshots of a remote application in a document | 
| US20170277738A1 (en) | 2015-01-29 | 2017-09-28 | Palantir Technologies Inc. | Temporal representation of structured information in an object model | 
| RU2596599C2 (en) * | 2015-02-03 | 2016-09-10 | Общество с ограниченной ответственностью "Аби ИнфоПоиск" | System and method of creating and using user ontology-based patterns for processing user text in natural language | 
| US9727560B2 (en) | 2015-02-25 | 2017-08-08 | Palantir Technologies Inc. | Systems and methods for organizing and identifying documents via hierarchies and dimensions of tags | 
| US9891808B2 (en) | 2015-03-16 | 2018-02-13 | Palantir Technologies Inc. | Interactive user interfaces for location-based data analysis | 
| US9886467B2 (en) | 2015-03-19 | 2018-02-06 | Plantir Technologies Inc. | System and method for comparing and visualizing data entities and data entity series | 
| US10103953B1 (en) | 2015-05-12 | 2018-10-16 | Palantir Technologies Inc. | Methods and systems for analyzing entity performance | 
| US9460175B1 (en) | 2015-06-03 | 2016-10-04 | Palantir Technologies Inc. | Server implemented geographic information system with graphical interface | 
| US20160357787A1 (en) * | 2015-06-05 | 2016-12-08 | Sap Se | Metadata extractor for software applications | 
| US9672257B2 (en) | 2015-06-05 | 2017-06-06 | Palantir Technologies Inc. | Time-series data storage and processing database system | 
| US9384203B1 (en) | 2015-06-09 | 2016-07-05 | Palantir Technologies Inc. | Systems and methods for indexing and aggregating data records | 
| US10628834B1 (en) | 2015-06-16 | 2020-04-21 | Palantir Technologies Inc. | Fraud lead detection system for efficiently processing database-stored data and automatically generating natural language explanatory information of system results for display in interactive user interfaces | 
| US9407652B1 (en) | 2015-06-26 | 2016-08-02 | Palantir Technologies Inc. | Network anomaly detection | 
| US9418337B1 (en) | 2015-07-21 | 2016-08-16 | Palantir Technologies Inc. | Systems and models for data analytics | 
| US9392008B1 (en) | 2015-07-23 | 2016-07-12 | Palantir Technologies Inc. | Systems and methods for identifying information related to payment card breaches | 
| US9454785B1 (en) | 2015-07-30 | 2016-09-27 | Palantir Technologies Inc. | Systems and user interfaces for holistic, data-driven investigation of bad actor behavior based on clustering and scoring of related data | 
| US9996595B2 (en) | 2015-08-03 | 2018-06-12 | Palantir Technologies, Inc. | Providing full data provenance visualization for versioned datasets | 
| US9456000B1 (en) | 2015-08-06 | 2016-09-27 | Palantir Technologies Inc. | Systems, methods, user interfaces, and computer-readable media for investigating potential malicious communications | 
| US10489391B1 (en) | 2015-08-17 | 2019-11-26 | Palantir Technologies Inc. | Systems and methods for grouping and enriching data items accessed from one or more databases for presentation in a user interface | 
| US9600146B2 (en) | 2015-08-17 | 2017-03-21 | Palantir Technologies Inc. | Interactive geospatial map | 
| US10102369B2 (en) | 2015-08-19 | 2018-10-16 | Palantir Technologies Inc. | Checkout system executable code monitoring, and user account compromise determination system | 
| US9537880B1 (en) | 2015-08-19 | 2017-01-03 | Palantir Technologies Inc. | Anomalous network monitoring, user behavior detection and database system | 
| US10127289B2 (en) | 2015-08-19 | 2018-11-13 | Palantir Technologies Inc. | Systems and methods for automatic clustering and canonical designation of related data in various data structures | 
| US10853378B1 (en) | 2015-08-25 | 2020-12-01 | Palantir Technologies Inc. | Electronic note management via a connected entity graph | 
| US11150917B2 (en) | 2015-08-26 | 2021-10-19 | Palantir Technologies Inc. | System for data aggregation and analysis of data from a plurality of data sources | 
| US10402385B1 (en) | 2015-08-27 | 2019-09-03 | Palantir Technologies Inc. | Database live reindex | 
| US9485265B1 (en) | 2015-08-28 | 2016-11-01 | Palantir Technologies Inc. | Malicious activity detection system capable of efficiently processing data accessed from databases and generating alerts for display in interactive user interfaces | 
| US10706434B1 (en) | 2015-09-01 | 2020-07-07 | Palantir Technologies Inc. | Methods and systems for determining location information | 
| US20170068712A1 (en) | 2015-09-04 | 2017-03-09 | Palantir Technologies Inc. | Systems and methods for database investigation tool | 
| US9984428B2 (en) | 2015-09-04 | 2018-05-29 | Palantir Technologies Inc. | Systems and methods for structuring data from unstructured electronic data files | 
| US9639580B1 (en) | 2015-09-04 | 2017-05-02 | Palantir Technologies, Inc. | Computer-implemented systems and methods for data management and visualization | 
| US9454564B1 (en) | 2015-09-09 | 2016-09-27 | Palantir Technologies Inc. | Data integrity checks | 
| US9576015B1 (en) | 2015-09-09 | 2017-02-21 | Palantir Technologies, Inc. | Domain-specific language for dataset transformations | 
| US10296617B1 (en) | 2015-10-05 | 2019-05-21 | Palantir Technologies Inc. | Searches of highly structured data | 
| US10044745B1 (en) | 2015-10-12 | 2018-08-07 | Palantir Technologies, Inc. | Systems for computer network security risk assessment including user compromise analysis associated with a network of devices | 
| US9424669B1 (en) | 2015-10-21 | 2016-08-23 | Palantir Technologies Inc. | Generating graphical representations of event participation flow | 
| US10223429B2 (en) | 2015-12-01 | 2019-03-05 | Palantir Technologies Inc. | Entity data attribution using disparate data sets | 
| US9514414B1 (en) | 2015-12-11 | 2016-12-06 | Palantir Technologies Inc. | Systems and methods for identifying and categorizing electronic documents through machine learning | 
| US9760556B1 (en) | 2015-12-11 | 2017-09-12 | Palantir Technologies Inc. | Systems and methods for annotating and linking electronic documents | 
| US9542446B1 (en) | 2015-12-17 | 2017-01-10 | Palantir Technologies, Inc. | Automatic generation of composite datasets based on hierarchical fields | 
| US10109094B2 (en) | 2015-12-21 | 2018-10-23 | Palantir Technologies Inc. | Interface to index and display geospatial data | 
| US9888039B2 (en) | 2015-12-28 | 2018-02-06 | Palantir Technologies Inc. | Network-based permissioning system | 
| US9996236B1 (en) | 2015-12-29 | 2018-06-12 | Palantir Technologies Inc. | Simplified frontend processing and visualization of large datasets | 
| US10268735B1 (en) | 2015-12-29 | 2019-04-23 | Palantir Technologies Inc. | Graph based resolution of matching items in data sources | 
| US9916465B1 (en) | 2015-12-29 | 2018-03-13 | Palantir Technologies Inc. | Systems and methods for automatic and customizable data minimization of electronic data stores | 
| US9823818B1 (en) | 2015-12-29 | 2017-11-21 | Palantir Technologies Inc. | Systems and interactive user interfaces for automatic generation of temporal representation of data objects | 
| US10621198B1 (en) | 2015-12-30 | 2020-04-14 | Palantir Technologies Inc. | System and method for secure database replication | 
| US9612723B1 (en) | 2015-12-30 | 2017-04-04 | Palantir Technologies Inc. | Composite graphical interface with shareable data-objects | 
| US10476975B2 (en) | 2015-12-31 | 2019-11-12 | Palantir Technologies Inc. | Building a user profile data repository | 
| US10698938B2 (en) | 2016-03-18 | 2020-06-30 | Palantir Technologies Inc. | Systems and methods for organizing and identifying documents via hierarchies and dimensions of tags | 
| US10068199B1 (en) | 2016-05-13 | 2018-09-04 | Palantir Technologies Inc. | System to catalogue tracking data | 
| US10169454B2 (en) * | 2016-05-17 | 2019-01-01 | Xerox Corporation | Unsupervised ontology-based graph extraction from texts | 
| US10498711B1 (en) | 2016-05-20 | 2019-12-03 | Palantir Technologies Inc. | Providing a booting key to a remote system | 
| US11243938B2 (en) * | 2016-05-31 | 2022-02-08 | Micro Focus Llc | Identifying data constraints in applications and databases | 
| US10007674B2 (en) | 2016-06-13 | 2018-06-26 | Palantir Technologies Inc. | Data revision control in large-scale data analytic systems | 
| US10084802B1 (en) | 2016-06-21 | 2018-09-25 | Palantir Technologies Inc. | Supervisory control and data acquisition | 
| US10291637B1 (en) | 2016-07-05 | 2019-05-14 | Palantir Technologies Inc. | Network anomaly detection and profiling | 
| US10324609B2 (en) | 2016-07-21 | 2019-06-18 | Palantir Technologies Inc. | System for providing dynamic linked panels in user interface | 
| US10719188B2 (en) | 2016-07-21 | 2020-07-21 | Palantir Technologies Inc. | Cached database and synchronization system for providing dynamic linked panels in user interface | 
| US12204845B2 (en) | 2016-07-21 | 2025-01-21 | Palantir Technologies Inc. | Cached database and synchronization system for providing dynamic linked panels in user interface | 
| US9686357B1 (en) | 2016-08-02 | 2017-06-20 | Palantir Technologies Inc. | Mapping content delivery | 
| US9753935B1 (en) | 2016-08-02 | 2017-09-05 | Palantir Technologies Inc. | Time-series data storage and processing database system | 
| US11106692B1 (en) | 2016-08-04 | 2021-08-31 | Palantir Technologies Inc. | Data record resolution and correlation system | 
| US10437840B1 (en) | 2016-08-19 | 2019-10-08 | Palantir Technologies Inc. | Focused probabilistic entity resolution from multiple data sources | 
| US10698927B1 (en) | 2016-08-30 | 2020-06-30 | Palantir Technologies Inc. | Multiple sensor session and log information compression and correlation system | 
| US9881066B1 (en) | 2016-08-31 | 2018-01-30 | Palantir Technologies, Inc. | Systems, methods, user interfaces and algorithms for performing database analysis and search of information involving structured and/or semi-structured data | 
| CN107818118B (en) * | 2016-09-14 | 2019-04-30 | 北京百度网讯科技有限公司 | Data storage method and device | 
| US10133588B1 (en) | 2016-10-20 | 2018-11-20 | Palantir Technologies Inc. | Transforming instructions for collaborative updates | 
| US11892987B2 (en) | 2016-10-20 | 2024-02-06 | Microsoft Technology Licensing, Llc | Automatic splitting of a column into multiple columns | 
| US11372830B2 (en) * | 2016-10-24 | 2022-06-28 | Microsoft Technology Licensing, Llc | Interactive splitting of a column into multiple columns | 
| US10102229B2 (en) | 2016-11-09 | 2018-10-16 | Palantir Technologies Inc. | Validating data integrations using a secondary data store | 
| US10318630B1 (en) | 2016-11-21 | 2019-06-11 | Palantir Technologies Inc. | Analysis of large bodies of textual data | 
| US10515433B1 (en) | 2016-12-13 | 2019-12-24 | Palantir Technologies Inc. | Zoom-adaptive data granularity to achieve a flexible high-performance interface for a geospatial mapping system | 
| US10884875B2 (en) | 2016-12-15 | 2021-01-05 | Palantir Technologies Inc. | Incremental backup of computer data files | 
| US9946777B1 (en) | 2016-12-19 | 2018-04-17 | Palantir Technologies Inc. | Systems and methods for facilitating data transformation | 
| GB201621627D0 (en) | 2016-12-19 | 2017-02-01 | Palantir Technologies Inc | Task allocation | 
| GB201621631D0 (en) | 2016-12-19 | 2017-02-01 | Palantir Technologies Inc | Predictive modelling | 
| GB201621623D0 (en) | 2016-12-19 | 2017-02-01 | Palantir Technologies Inc | Determining maintenance for a machine | 
| GB201621622D0 (en) | 2016-12-19 | 2017-02-01 | Palantir Technologies Inc | Machine fault modelling | 
| US10270727B2 (en) | 2016-12-20 | 2019-04-23 | Palantir Technologies, Inc. | Short message communication within a mobile graphical map | 
| US10728262B1 (en) | 2016-12-21 | 2020-07-28 | Palantir Technologies Inc. | Context-aware network-based malicious activity warning systems | 
| US10223099B2 (en) | 2016-12-21 | 2019-03-05 | Palantir Technologies Inc. | Systems and methods for peer-to-peer build sharing | 
| US10262053B2 (en) | 2016-12-22 | 2019-04-16 | Palantir Technologies Inc. | Systems and methods for data replication synchronization | 
| US11373752B2 (en) | 2016-12-22 | 2022-06-28 | Palantir Technologies Inc. | Detection of misuse of a benefit system | 
| US10721262B2 (en) | 2016-12-28 | 2020-07-21 | Palantir Technologies Inc. | Resource-centric network cyber attack warning system | 
| US10460602B1 (en) | 2016-12-28 | 2019-10-29 | Palantir Technologies Inc. | Interactive vehicle information mapping system | 
| US10552436B2 (en) | 2016-12-28 | 2020-02-04 | Palantir Technologies Inc. | Systems and methods for retrieving and processing data for display | 
| US10754872B2 (en) | 2016-12-28 | 2020-08-25 | Palantir Technologies Inc. | Automatically executing tasks and configuring access control lists in a data transformation system | 
| US9922108B1 (en) | 2017-01-05 | 2018-03-20 | Palantir Technologies Inc. | Systems and methods for facilitating data transformation | 
| US10579689B2 (en) | 2017-02-08 | 2020-03-03 | International Business Machines Corporation | Visualization and augmentation of human knowledge construction during material consumption | 
| US10579239B1 (en) | 2017-03-23 | 2020-03-03 | Palantir Technologies Inc. | Systems and methods for production and display of dynamically linked slide presentations | 
| US10475219B1 (en) | 2017-03-30 | 2019-11-12 | Palantir Technologies Inc. | Multidimensional arc chart for visual comparison | 
| US10068002B1 (en) | 2017-04-25 | 2018-09-04 | Palantir Technologies Inc. | Systems and methods for adaptive data replication | 
| US11074277B1 (en) | 2017-05-01 | 2021-07-27 | Palantir Technologies Inc. | Secure resolution of canonical entities | 
| US10896097B1 (en) | 2017-05-25 | 2021-01-19 | Palantir Technologies Inc. | Approaches for backup and restoration of integrated databases | 
| US11334216B2 (en) | 2017-05-30 | 2022-05-17 | Palantir Technologies Inc. | Systems and methods for visually presenting geospatial information | 
| US10895946B2 (en) | 2017-05-30 | 2021-01-19 | Palantir Technologies Inc. | Systems and methods for using tiled data | 
| US10430062B2 (en) | 2017-05-30 | 2019-10-01 | Palantir Technologies Inc. | Systems and methods for geo-fenced dynamic dissemination | 
| GB201708818D0 (en) | 2017-06-02 | 2017-07-19 | Palantir Technologies Inc | Systems and methods for retrieving and processing data | 
| US10956406B2 (en) | 2017-06-12 | 2021-03-23 | Palantir Technologies Inc. | Propagated deletion of database records and derived data | 
| US11030494B1 (en) | 2017-06-15 | 2021-06-08 | Palantir Technologies Inc. | Systems and methods for managing data spills | 
| US10027551B1 (en) | 2017-06-29 | 2018-07-17 | Palantir Technologies, Inc. | Access controls through node-based effective policy identifiers | 
| US10691729B2 (en) | 2017-07-07 | 2020-06-23 | Palantir Technologies Inc. | Systems and methods for providing an object platform for a relational database | 
| US10628002B1 (en) | 2017-07-10 | 2020-04-21 | Palantir Technologies Inc. | Integrated data authentication system with an interactive user interface | 
| US10403011B1 (en) | 2017-07-18 | 2019-09-03 | Palantir Technologies Inc. | Passing system with an interactive user interface | 
| US10706038B2 (en) * | 2017-07-27 | 2020-07-07 | Cisco Technology, Inc. | System and method for state object data store | 
| US11334552B2 (en) | 2017-07-31 | 2022-05-17 | Palantir Technologies Inc. | Lightweight redundancy tool for performing transactions | 
| US10417224B2 (en) | 2017-08-14 | 2019-09-17 | Palantir Technologies Inc. | Time series database processing system | 
| US10963465B1 (en) | 2017-08-25 | 2021-03-30 | Palantir Technologies Inc. | Rapid importation of data including temporally tracked object recognition | 
| US10984427B1 (en) | 2017-09-13 | 2021-04-20 | Palantir Technologies Inc. | Approaches for analyzing entity relationships | 
| US10216695B1 (en) | 2017-09-21 | 2019-02-26 | Palantir Technologies Inc. | Database system for time series data storage, processing, and analysis | 
| US10079832B1 (en) | 2017-10-18 | 2018-09-18 | Palantir Technologies Inc. | Controlling user creation of data resources on a data processing platform | 
| GB201716170D0 (en) | 2017-10-04 | 2017-11-15 | Palantir Technologies Inc | Controlling user creation of data resources on a data processing platform | 
| US10956508B2 (en) | 2017-11-10 | 2021-03-23 | Palantir Technologies Inc. | Systems and methods for creating and managing a data integration workspace containing automatically updated data models | 
| CN107861725B (en) * | 2017-11-22 | 2020-12-22 | 北京酷我科技有限公司 | iOS data reverse automatic analysis strategy | 
| CN107977226A (en) * | 2017-11-22 | 2018-05-01 | 北京酷我科技有限公司 | A kind of positive automatic parsing strategy of iOS data | 
| CN108008957B (en) * | 2017-11-23 | 2023-01-17 | 北京酷我科技有限公司 | Data reverse analysis method in iOS | 
| CN107943483B (en) * | 2017-11-23 | 2023-03-24 | 北京酷我科技有限公司 | Data forward analysis method in iOS | 
| US10371537B1 (en) | 2017-11-29 | 2019-08-06 | Palantir Technologies Inc. | Systems and methods for flexible route planning | 
| US10250401B1 (en) | 2017-11-29 | 2019-04-02 | Palantir Technologies Inc. | Systems and methods for providing category-sensitive chat channels | 
| US11281726B2 (en) | 2017-12-01 | 2022-03-22 | Palantir Technologies Inc. | System and methods for faster processor comparisons of visual graph features | 
| US10614069B2 (en) | 2017-12-01 | 2020-04-07 | Palantir Technologies Inc. | Workflow driven database partitioning | 
| US10235533B1 (en) | 2017-12-01 | 2019-03-19 | Palantir Technologies Inc. | Multi-user access controls in electronic simultaneously editable document editor | 
| US11016986B2 (en) | 2017-12-04 | 2021-05-25 | Palantir Technologies Inc. | Query-based time-series data display and processing system | 
| US11599706B1 (en) | 2017-12-06 | 2023-03-07 | Palantir Technologies Inc. | Systems and methods for providing a view of geospatial information | 
| US11133925B2 (en) | 2017-12-07 | 2021-09-28 | Palantir Technologies Inc. | Selective access to encrypted logs | 
| US10380196B2 (en) | 2017-12-08 | 2019-08-13 | Palantir Technologies Inc. | Systems and methods for using linked documents | 
| US11061874B1 (en) | 2017-12-14 | 2021-07-13 | Palantir Technologies Inc. | Systems and methods for resolving entity data across various data structures | 
| US10929476B2 (en) | 2017-12-14 | 2021-02-23 | Palantir Technologies Inc. | Systems and methods for visualizing and analyzing multi-dimensional data | 
| US10698756B1 (en) | 2017-12-15 | 2020-06-30 | Palantir Technologies Inc. | Linking related events for various devices and services in computer log files on a centralized server | 
| US10915542B1 (en) | 2017-12-19 | 2021-02-09 | Palantir Technologies Inc. | Contextual modification of data sharing constraints in a distributed database system that uses a multi-master replication scheme | 
| US10838987B1 (en) | 2017-12-20 | 2020-11-17 | Palantir Technologies Inc. | Adaptive and transparent entity screening | 
| US10853352B1 (en) | 2017-12-21 | 2020-12-01 | Palantir Technologies Inc. | Structured data collection, presentation, validation and workflow management | 
| US10142349B1 (en) | 2018-02-22 | 2018-11-27 | Palantir Technologies Inc. | Verifying network-based permissioning rights | 
| US11599369B1 (en) | 2018-03-08 | 2023-03-07 | Palantir Technologies Inc. | Graphical user interface configuration system | 
| US10896234B2 (en) | 2018-03-29 | 2021-01-19 | Palantir Technologies Inc. | Interactive geographical map | 
| US10878051B1 (en) | 2018-03-30 | 2020-12-29 | Palantir Technologies Inc. | Mapping device identifiers | 
| US10255415B1 (en) | 2018-04-03 | 2019-04-09 | Palantir Technologies Inc. | Controlling access to computer resources | 
| US10830599B2 (en) | 2018-04-03 | 2020-11-10 | Palantir Technologies Inc. | Systems and methods for alternative projections of geographical information | 
| US11585672B1 (en) | 2018-04-11 | 2023-02-21 | Palantir Technologies Inc. | Three-dimensional representations of routes | 
| US10754822B1 (en) | 2018-04-18 | 2020-08-25 | Palantir Technologies Inc. | Systems and methods for ontology migration | 
| US10885021B1 (en) | 2018-05-02 | 2021-01-05 | Palantir Technologies Inc. | Interactive interpreter and graphical user interface | 
| GB201807534D0 (en) | 2018-05-09 | 2018-06-20 | Palantir Technologies Inc | Systems and methods for indexing and searching | 
| US10949400B2 (en) | 2018-05-09 | 2021-03-16 | Palantir Technologies Inc. | Systems and methods for tamper-resistant activity logging | 
| US11461355B1 (en) | 2018-05-15 | 2022-10-04 | Palantir Technologies Inc. | Ontological mapping of data | 
| US12271376B1 (en) * | 2018-05-18 | 2025-04-08 | Amazon Technologies, Inc. | Generating metadata from a scan of a data object in an object store for performing subsequent queries to the data object | 
| US10429197B1 (en) | 2018-05-29 | 2019-10-01 | Palantir Technologies Inc. | Terrain analysis for automatic route determination | 
| US11061542B1 (en) | 2018-06-01 | 2021-07-13 | Palantir Technologies Inc. | Systems and methods for determining and displaying optimal associations of data items | 
| US11244063B2 (en) | 2018-06-11 | 2022-02-08 | Palantir Technologies Inc. | Row-level and column-level policy service | 
| US10795909B1 (en) | 2018-06-14 | 2020-10-06 | Palantir Technologies Inc. | Minimized and collapsed resource dependency path | 
| US11119630B1 (en) | 2018-06-19 | 2021-09-14 | Palantir Technologies Inc. | Artificial intelligence assisted evaluations and user interface for same | 
| US11210349B1 (en) | 2018-08-02 | 2021-12-28 | Palantir Technologies Inc. | Multi-database document search system architecture | 
| US10467435B1 (en) | 2018-10-24 | 2019-11-05 | Palantir Technologies Inc. | Approaches for managing restrictions for middleware applications | 
| US11025672B2 (en) | 2018-10-25 | 2021-06-01 | Palantir Technologies Inc. | Approaches for securing middleware data access | 
| US10659751B1 (en) * | 2018-12-14 | 2020-05-19 | Lyft Inc. | Multichannel, multi-polarization imaging for improved perception | 
| EP3694173B1 (en) | 2019-02-08 | 2022-09-21 | Palantir Technologies Inc. | Isolating applications associated with multiple tenants within a computing platform | 
| GB201908091D0 (en) | 2019-06-06 | 2019-07-24 | Palantir Technologies Inc | Time series databases | 
| US11704441B2 (en) | 2019-09-03 | 2023-07-18 | Palantir Technologies Inc. | Charter-based access controls for managing computer resources | 
| EP3796165A1 (en) | 2019-09-18 | 2021-03-24 | Palantir Technologies Inc. | Systems and methods for autoscaling instance groups of computing platforms | 
| US12353678B2 (en) | 2019-10-17 | 2025-07-08 | Palantir Technologies Inc. | Object-centric data analysis system and associated graphical user interfaces | 
| US11074476B2 (en) * | 2019-11-21 | 2021-07-27 | AstrumU, Inc. | Data ingestion platform | 
| US11514334B2 (en) | 2020-02-07 | 2022-11-29 | International Business Machines Corporation | Maintaining a knowledge database based on user interactions with a user interface | 
| US11609893B1 (en) | 2020-05-27 | 2023-03-21 | The Mathworks, Inc. | Systems and methods for generating and modifying a pattern for pattern matching utilizing a hierarchical structure that stores one or more values | 
| US11151673B1 (en) | 2020-06-10 | 2021-10-19 | AstrumU, Inc. | Correlating education programs and employment objectives | 
| US11074509B1 (en) | 2020-10-30 | 2021-07-27 | AstrumU, Inc. | Predictive learner score | 
| US11928607B2 (en) | 2020-10-30 | 2024-03-12 | AstrumU, Inc. | Predictive learner recommendation platform | 
| KR102429855B1 (en) * | 2022-01-26 | 2022-08-05 | 주식회사 에스투더블유 | Method to store and analyze file-based log data for various models | 
| US11714956B1 (en) * | 2022-01-27 | 2023-08-01 | Rakuten Mobile, Inc. | Ontology-based semantic rendering | 
| US12248898B2 (en) | 2022-01-28 | 2025-03-11 | AstrumU, Inc. | Confirming skills and proficiency in course offerings | 
| US11847172B2 (en) | 2022-04-29 | 2023-12-19 | AstrumU, Inc. | Unified graph representation of skills and acumen | 
| KR102638529B1 (en) | 2023-08-17 | 2024-02-20 | 주식회사 파워이십일 | Ontology data management system and method for interfacing with power system applications | 
| US12099975B1 (en) | 2023-10-13 | 2024-09-24 | AstrumU, Inc. | System for analyzing learners | 
| US12596619B2 (en) * | 2024-01-12 | 2026-04-07 | Rubrik, Inc. | Techniques for identifying semantic change in metadata | 
| US12307799B1 (en) | 2024-09-23 | 2025-05-20 | AstrumU, Inc. | Document ingestion pipeline | 
Citations (213)
| Publication number | Priority date | Publication date | Assignee | Title | 
|---|---|---|---|---|
| US5241625A (en) | 1990-11-27 | 1993-08-31 | Farallon Computing, Inc. | Screen image sharing among heterogeneous computers | 
| US5845300A (en) | 1996-06-05 | 1998-12-01 | Microsoft Corporation | Method and apparatus for suggesting completions for a partially entered data item based on previously-entered, associated data items | 
| US5999911A (en) | 1995-06-02 | 1999-12-07 | Mentor Graphics Corporation | Method and system for managing workflow | 
| US6065026A (en) | 1997-01-09 | 2000-05-16 | Document.Com, Inc. | Multi-user electronic document authoring system with prompted updating of shared language | 
| WO2001025906A1 (en) | 1999-10-01 | 2001-04-12 | Global Graphics Software Limited | Method and system for arranging a workflow using graphical user interface | 
| US6232971B1 (en) | 1998-09-23 | 2001-05-15 | International Business Machines Corporation | Variable modality child windows | 
| US6237138B1 (en) | 1996-11-12 | 2001-05-22 | International Business Machines Corp. | Buffered screen capturing software tool for usability testing of computer applications | 
| US6243706B1 (en) | 1998-07-24 | 2001-06-05 | Avid Technology, Inc. | System and method for managing the creation and production of computer generated works | 
| US6289338B1 (en) | 1997-12-15 | 2001-09-11 | Manning & Napier Information Services | Database analysis using a probabilistic ontology | 
| WO2001088750A1 (en) | 2000-05-16 | 2001-11-22 | Carroll Garrett O | A document processing system and method | 
| GB2366498A (en) | 2000-08-25 | 2002-03-06 | Copyn Ltd | Method of bookmarking a section of a web-page and storing said bookmarks | 
| US20020032677A1 (en) | 2000-03-01 | 2002-03-14 | Jeff Morgenthaler | Methods for creating, editing, and updating searchable graphical database and databases of graphical images and information and displaying graphical images from a searchable graphical database or databases in a sequential or slide show format | 
| US6370538B1 (en) | 1999-11-22 | 2002-04-09 | Xerox Corporation | Direct manipulation interface for document properties | 
| US20020095360A1 (en) | 2001-01-16 | 2002-07-18 | Joao Raymond Anthony | Apparatus and method for providing transaction history information, account history information, and/or charge-back information | 
| US20020103705A1 (en) | 2000-12-06 | 2002-08-01 | Forecourt Communication Group | Method and apparatus for using prior purchases to select activities to present to a customer | 
| US6430305B1 (en) | 1996-12-20 | 2002-08-06 | Synaptics, Incorporated | Identity verification methods | 
| US6463404B1 (en) | 1997-08-08 | 2002-10-08 | British Telecommunications Public Limited Company | Translation | 
| US20020194201A1 (en) * | 2001-06-05 | 2002-12-19 | Wilbanks John Thompson | Systems, methods and computer program products for integrating biological/chemical databases to create an ontology network | 
| US20020196229A1 (en) | 2001-06-26 | 2002-12-26 | Frank Chen | Graphics-based calculator capable of directly editing data points on graph | 
| US6523172B1 (en) * | 1998-12-17 | 2003-02-18 | Evolutionary Technologies International, Inc. | Parser translator system and method | 
| US6523019B1 (en) | 1999-09-21 | 2003-02-18 | Choicemaker Technologies, Inc. | Probabilistic record linkage model derived from training data | 
| US20030036927A1 (en) | 2001-08-20 | 2003-02-20 | Bowen Susan W. | Healthcare information search system and user interface | 
| US6539538B1 (en) | 1995-11-13 | 2003-03-25 | Concerto Software, Inc. | Intelligent information routing system and method | 
| US20030126102A1 (en) | 1999-09-21 | 2003-07-03 | Choicemaker Technologies, Inc. | Probabilistic record linkage model derived from training data | 
| WO2003060751A1 (en) | 2001-12-26 | 2003-07-24 | Compassoft, Inc. | System and method for autonomously generating heterogeneous data source interoperability bridges based on semantic modeling derived from self adapting ontology | 
| WO2002035376A3 (en) | 2000-10-27 | 2003-08-28 | Science Applic Int Corp | Ontology-based parser for natural language processing | 
| US20030172053A1 (en) | 2002-02-01 | 2003-09-11 | John Fairweather | System and method for mining data | 
| US20030177112A1 (en) * | 2002-01-28 | 2003-09-18 | Steve Gardner | Ontology-based information management system and method | 
| US6640231B1 (en) | 2000-10-06 | 2003-10-28 | Ontology Works, Inc. | Ontology for database design and application development | 
| US6665683B1 (en) | 2001-06-22 | 2003-12-16 | E. Intelligence, Inc. | System and method for adjusting a value within a multidimensional aggregation tree | 
| US20040034570A1 (en) | 2002-03-20 | 2004-02-19 | Mark Davis | Targeted incentives based upon predicted behavior | 
| US20040044992A1 (en) | 2002-09-03 | 2004-03-04 | Horst Muller | Handling parameters in test scripts for computer program applications | 
| US20040044648A1 (en) | 2002-06-24 | 2004-03-04 | Xmyphonic System As | Method for data-centric collaboration | 
| US20040083466A1 (en) * | 2002-10-29 | 2004-04-29 | Dapp Michael C. | Hardware parser accelerator | 
| US6748481B1 (en) | 1999-04-06 | 2004-06-08 | Microsoft Corporation | Streaming information appliance with circular buffer for receiving and selectively reading blocks of streaming information | 
| US20040205492A1 (en) | 2001-07-26 | 2004-10-14 | Newsome Mark R. | Content clipping service | 
| US20040221223A1 (en) | 2003-04-29 | 2004-11-04 | Nam-Yul Yu | Apparatus and method for encoding a low density parity check code | 
| US20040236711A1 (en) | 2003-05-21 | 2004-11-25 | Bentley Systems, Inc. | System and method for automating the extraction of information contained within an engineering document | 
| US20040236688A1 (en) | 2000-10-30 | 2004-11-25 | Bozeman William O. | Universal positive pay database method, system, and computer useable medium | 
| US20050010472A1 (en) | 2003-07-08 | 2005-01-13 | Quatse Jesse T. | High-precision customer-based targeting by individual usage statistics | 
| US6850317B2 (en) | 2001-01-23 | 2005-02-01 | Schlumberger Technology Corporation | Apparatus and methods for determining velocity of oil in a flow stream | 
| US20050028094A1 (en) | 1999-07-30 | 2005-02-03 | Microsoft Corporation | Modeless child windows for application programs | 
| US20050039119A1 (en) | 2003-08-12 | 2005-02-17 | Accenture Global Services Gmbh | Presentation generator | 
| US20050039116A1 (en) | 2003-07-31 | 2005-02-17 | Canon Kabushiki Kaisha | Collaborative editing with automatic layout | 
| US6877137B1 (en) | 1998-04-09 | 2005-04-05 | Rose Blush Software Llc | System, method and computer program product for mediating notes and note sub-notes linked or otherwise associated with stored or networked web pages | 
| US20050091186A1 (en) | 2003-10-24 | 2005-04-28 | Alon Elish | Integrated method and apparatus for capture, storage, and retrieval of information | 
| US20050091420A1 (en) | 2003-10-24 | 2005-04-28 | Microsoft Corporation | Mechanism for handling input parameters | 
| US20050125715A1 (en) | 2003-12-04 | 2005-06-09 | Fabrizio Di Franco | Method of saving data in a graphical user interface | 
| US20050183005A1 (en) | 2004-02-12 | 2005-08-18 | Laurent Denoue | Systems and methods for freeform annotations | 
| US6944821B1 (en) | 1999-12-07 | 2005-09-13 | International Business Machines Corporation | Copy/paste mechanism and paste buffer that includes source information for copied data | 
| US6967589B1 (en) | 2000-08-11 | 2005-11-22 | Oleumtech Corporation | Gas/oil well monitoring system | 
| US20060026561A1 (en) | 2004-07-29 | 2006-02-02 | International Business Machines Corporation | Inserting into a document a screen image of a computer software application | 
| US20060031779A1 (en) | 2004-04-15 | 2006-02-09 | Citrix Systems, Inc. | Selectively sharing screen data | 
| US20060053170A1 (en) | 2004-09-03 | 2006-03-09 | Bio Wisdom Limited | System and method for parsing and/or exporting data from one or more multi-relational ontologies | 
| US20060053097A1 (en) | 2004-04-01 | 2006-03-09 | King Martin T | Searching and accessing documents on private networks for use with captures from rendered documents | 
| US20060059423A1 (en) | 2004-09-13 | 2006-03-16 | Stefan Lehmann | Apparatus, system, and method for creating customized workflow documentation | 
| US20060080139A1 (en) | 2004-10-08 | 2006-04-13 | Woodhaven Health Services | Preadmission health care cost and reimbursement estimation tool | 
| US20060123027A1 (en) * | 2003-02-10 | 2006-06-08 | Joern Kohlhammer | Time-critical filtering of information using domain ontologies | 
| US20060129746A1 (en) | 2004-12-14 | 2006-06-15 | Ithink, Inc. | Method and graphic interface for storing, moving, sending or printing electronic data to two or more locations, in two or more formats with a single save function | 
| EP1672527A2 (en) | 2004-12-15 | 2006-06-21 | Microsoft Corporation | System and method for automatically completing spreadsheet formulas | 
| US20060136513A1 (en) | 2004-12-21 | 2006-06-22 | Nextpage, Inc. | Managing the status of documents in a distributed storage system | 
| US20060143075A1 (en) | 2003-09-22 | 2006-06-29 | Ryan Carr | Assumed demographics, predicted behaviour, and targeted incentives | 
| US20060155654A1 (en) | 2002-08-13 | 2006-07-13 | Frederic Plessis | Editor and method for editing formulae for calculating the price of a service and a system for automatic costing of a service | 
| US7086028B1 (en) | 2003-04-09 | 2006-08-01 | Autodesk, Inc. | Simplified generation of design change information on a drawing in a computer aided design (CAD) environment | 
| US7089541B2 (en) | 2001-11-30 | 2006-08-08 | Sun Microsystems, Inc. | Modular parser architecture with mini parsers | 
| US20060178915A1 (en) | 2002-10-18 | 2006-08-10 | Schumarry Chao | Mass customization for management of healthcare | 
| US20060218163A1 (en) | 2005-03-28 | 2006-09-28 | Microsoft Corporation | Rapid prototyping database | 
| US20060265417A1 (en) | 2004-05-04 | 2006-11-23 | Amato Jerry S | Enhanced graphical interfaces for displaying visual data | 
| US20060277460A1 (en) | 2005-06-03 | 2006-12-07 | Scott Forstall | Webview applications | 
| US20070000999A1 (en) | 2005-06-06 | 2007-01-04 | First Data Corporation | System and method for authorizing electronic payment transactions | 
| US7174377B2 (en) | 2002-01-16 | 2007-02-06 | Xerox Corporation | Method and apparatus for collaborative document versioning of networked documents | 
| US20070043686A1 (en) | 2005-08-22 | 2007-02-22 | International Business Machines Corporation | Xml sub-document versioning method in xml databases using record storages | 
| US20070061752A1 (en) | 2005-09-15 | 2007-03-15 | Microsoft Corporation | Cross-application support of charts | 
| US7194680B1 (en) | 1999-12-07 | 2007-03-20 | Adobe Systems Incorporated | Formatting content by example | 
| US20070074169A1 (en) | 2005-08-25 | 2007-03-29 | Fortify Software, Inc. | Apparatus and method for analyzing and supplementing a program to provide security | 
| US20070078872A1 (en) | 2005-09-30 | 2007-04-05 | Ronen Cohen | Apparatus and method for parsing unstructured data | 
| US7213030B1 (en) | 1998-10-16 | 2007-05-01 | Jenkins Steven R | Web-enabled transaction and collaborative management system | 
| US20070113164A1 (en) | 2000-05-17 | 2007-05-17 | Hansen David R | System and method for implementing compound documents in a production printing workflow | 
| US20070136095A1 (en) | 2005-12-09 | 2007-06-14 | Arizona Board Of Regents On Behalf Of The University Of Arizona | Icon Queues for Workflow Management | 
| US7237192B1 (en) | 2002-04-30 | 2007-06-26 | Oracle International Corporation | Methods and systems for naming and indexing children in a hierarchical nodal structure | 
| US20070185850A1 (en) | 1999-11-10 | 2007-08-09 | Walters Edward J | Apparatus and Method for Displaying Records Responsive to a Database Query | 
| US20070233709A1 (en) | 2006-03-30 | 2007-10-04 | Emc Corporation | Smart containers | 
| US20070245339A1 (en) | 2006-04-12 | 2007-10-18 | Bauman Brian D | Creating documentation screenshots on demand | 
| WO2007133206A1 (en) | 2006-05-12 | 2007-11-22 | Drawing Management Incorporated | Spatial graphical user interface and method for using the same | 
| US20070284433A1 (en) | 2006-06-08 | 2007-12-13 | American Express Travel Related Services Company, Inc. | Method, system, and computer program product for customer-level data verification | 
| US20070299697A1 (en) | 2004-10-12 | 2007-12-27 | Friedlander Robert R | Methods for Associating Records in Healthcare Databases with Individuals | 
| US20080016155A1 (en) | 2006-07-11 | 2008-01-17 | Igor Khalatian | One-Click Universal Screen Sharing | 
| US20080091693A1 (en) | 2006-10-16 | 2008-04-17 | Oracle International Corporation | Managing compound XML documents in a repository | 
| US20080109714A1 (en) | 2006-11-03 | 2008-05-08 | Sap Ag | Capturing screen information | 
| WO2008064207A2 (en) | 2006-11-20 | 2008-05-29 | Palantir Technologies, Inc. | Creating data in a data store using a dynamic ontology | 
| US20080140387A1 (en) | 2006-12-07 | 2008-06-12 | Linker Sheldon O | Method and system for machine understanding, knowledge, and conversation | 
| US20080148398A1 (en) | 2006-10-31 | 2008-06-19 | Derek John Mezack | System and Method for Definition and Automated Analysis of Computer Security Threat Models | 
| US20080172607A1 (en) | 2007-01-15 | 2008-07-17 | Microsoft Corporation | Selective Undo of Editing Operations Performed on Data Objects | 
| US20080177782A1 (en) | 2007-01-10 | 2008-07-24 | Pado Metaware Ab | Method and system for facilitating the production of documents | 
| US20080228467A1 (en) | 2004-01-06 | 2008-09-18 | Neuric Technologies, Llc | Natural language parsing method to provide conceptual flow | 
| US20080249820A1 (en) | 2002-02-15 | 2008-10-09 | Pathria Anu K | Consistency modeling of healthcare claims to detect fraud and abuse | 
| US7441219B2 (en) | 2003-06-24 | 2008-10-21 | National Semiconductor Corporation | Method for creating, modifying, and simulating electrical circuits over the internet | 
| US7441182B2 (en) | 2003-10-23 | 2008-10-21 | Microsoft Corporation | Digital negatives | 
| US20080281580A1 (en) | 2007-05-10 | 2008-11-13 | Microsoft Corporation | Dynamic parser | 
| US20080313243A1 (en) | 2007-05-24 | 2008-12-18 | Pado Metaware Ab | method and system for harmonization of variants of a sequential file | 
| US20080313132A1 (en) | 2007-06-15 | 2008-12-18 | Fang Hao | High accuracy bloom filter using partitioned hashing | 
| US20090031401A1 (en) | 2007-04-27 | 2009-01-29 | Bea Systems, Inc. | Annotations for enterprise web application constructor | 
| US20090043801A1 (en) | 2007-08-06 | 2009-02-12 | Intuit Inc. | Method and apparatus for selecting a doctor based on an observed experience level | 
| US20090089651A1 (en) | 2007-09-27 | 2009-04-02 | Tilman Herberger | System and method for dynamic content insertion from the internet into a multimedia work | 
| US20090106178A1 (en) | 2007-10-23 | 2009-04-23 | Sas Institute Inc. | Computer-Implemented Systems And Methods For Updating Predictive Models | 
| US20090112678A1 (en) | 2007-10-26 | 2009-04-30 | Ingram Micro Inc. | System and method for knowledge management | 
| US20090112745A1 (en) | 2007-10-30 | 2009-04-30 | Intuit Inc. | Technique for reducing phishing | 
| US20090150868A1 (en) | 2007-12-10 | 2009-06-11 | Al Chakra | Method and System for Capturing Movie Shots at the Time of an Automated Graphical User Interface Test Failure | 
| US20090172821A1 (en) | 2004-06-30 | 2009-07-02 | Faycal Daira | System and method for securing computer stations and/or communication networks | 
| US20090177962A1 (en) | 2008-01-04 | 2009-07-09 | Microsoft Corporation | Intelligently representing files in a view | 
| US20090187546A1 (en) | 2008-01-21 | 2009-07-23 | International Business Machines Corporation | Method, System and Computer Program Product for Duplicate Detection | 
| US20090199106A1 (en) | 2008-02-05 | 2009-08-06 | Sony Ericsson Mobile Communications Ab | Communication terminal including graphical bookmark manager | 
| US20090249178A1 (en) | 2008-04-01 | 2009-10-01 | Ambrosino Timothy J | Document linking | 
| US20090248757A1 (en) | 2008-04-01 | 2009-10-01 | Microsoft Corporation | Application-Managed File Versioning | 
| US20090254970A1 (en) | 2008-04-04 | 2009-10-08 | Avaya Inc. | Multi-tier security event correlation and mitigation | 
| US20090271343A1 (en) | 2008-04-25 | 2009-10-29 | Anthony Vaiciulis | Automated entity identification for efficient profiling in an event probability prediction system | 
| US20090281839A1 (en) | 2002-05-17 | 2009-11-12 | Lawrence A. Lynn | Patient safety processor | 
| US20090282068A1 (en) | 2008-05-12 | 2009-11-12 | Shockro John J | Semantic packager | 
| US20090307049A1 (en) | 2008-06-05 | 2009-12-10 | Fair Isaac Corporation | Soft Co-Clustering of Data | 
| US20090313463A1 (en) | 2005-11-01 | 2009-12-17 | Commonwealth Scientific And Industrial Research Organisation | Data matching using data clusters | 
| US20090319891A1 (en) | 2008-06-22 | 2009-12-24 | Mackinlay Jock Douglas | Methods and systems of automatically generating marks in a graphical view | 
| US20100011282A1 (en) | 2008-07-11 | 2010-01-14 | iCyte Pty Ltd. | Annotation system and method | 
| US20100057622A1 (en) | 2001-02-27 | 2010-03-04 | Faith Patrick L | Distributed Quantum Encrypted Pattern Generation And Scoring | 
| WO2010030913A2 (en) | 2008-09-15 | 2010-03-18 | Palantir Technologies, Inc. | Modal-less interface enhancements | 
| US20100098318A1 (en) | 2008-10-20 | 2010-04-22 | Jpmorgan Chase Bank, N.A. | Method and System for Duplicate Check Detection | 
| US7765489B1 (en) | 2008-03-03 | 2010-07-27 | Shah Shalin N | Presenting notifications related to a medical study on a toolbar | 
| US20100204983A1 (en) | 2004-08-06 | 2010-08-12 | Kevin Chen-Chuan Chung | Method and System for Extracting Web Query Interfaces | 
| EP2221725A1 (en) | 2009-02-19 | 2010-08-25 | Mecel Aktiebolag | Validator for validating conformity of a software configuration | 
| US20100223260A1 (en) | 2004-05-06 | 2010-09-02 | Oracle International Corporation | Web Server for Multi-Version Web Documents | 
| US20100238174A1 (en) | 2009-03-18 | 2010-09-23 | Andreas Peter Haub | Cursor Synchronization in a Plurality of Graphs | 
| US20100262901A1 (en) | 2005-04-14 | 2010-10-14 | Disalvo Dean F | Engineering process for a real-time user-defined data collection, analysis, and optimization tool (dot) | 
| US20100280851A1 (en) | 2005-02-22 | 2010-11-04 | Richard Merkin | Systems and methods for assessing and optimizing healthcare administration | 
| US20100306285A1 (en) | 2009-05-28 | 2010-12-02 | Arcsight, Inc. | Specifying a Parser Using a Properties File | 
| US20100313239A1 (en) | 2009-06-09 | 2010-12-09 | International Business Machines Corporation | Automated access control for rendered output | 
| US20100313119A1 (en) | 2009-06-05 | 2010-12-09 | Microsoft Corporation | In-line dynamic text with variable formatting | 
| US7877421B2 (en) | 2001-05-25 | 2011-01-25 | International Business Machines Corporation | Method and system for mapping enterprise data assets to a semantic information model | 
| US7880921B2 (en) | 2007-05-01 | 2011-02-01 | Michael Joseph Dattilo | Method and apparatus to digitally whiteout mistakes on a printed form | 
| US20110047540A1 (en) | 2009-08-24 | 2011-02-24 | Embarcadero Technologies Inc. | System and Methodology for Automating Delivery, Licensing, and Availability of Software Products | 
| US20110074788A1 (en) | 2009-09-30 | 2011-03-31 | Mckesson Financial Holdings Limited | Methods, apparatuses, and computer program products for facilitating visualization and analysis of medical data | 
| US20110093327A1 (en) | 2009-10-15 | 2011-04-21 | Visa U.S.A. Inc. | Systems and Methods to Match Identifiers | 
| US20110099133A1 (en) | 2009-10-28 | 2011-04-28 | Industrial Technology Research Institute | Systems and methods for capturing and managing collective social intelligence information | 
| US7941336B1 (en) | 2005-09-14 | 2011-05-10 | D2C Solutions, LLC | Segregation-of-duties analysis apparatus and method | 
| US7958147B1 (en) | 2005-09-13 | 2011-06-07 | James Luke Turner | Method for providing customized and automated security assistance, a document marking regime, and central tracking and control for sensitive or classified documents in electronic format | 
| WO2011071833A1 (en) | 2009-12-07 | 2011-06-16 | Accenture Global Services Gmbh | Method and system for accelerated data quality enhancement | 
| US7966199B1 (en) | 2007-07-19 | 2011-06-21 | Intuit Inc. | Method and system for identification of geographic condition zones using aggregated claim data | 
| US20110161409A1 (en) | 2008-06-02 | 2011-06-30 | Azuki Systems, Inc. | Media mashup system | 
| US20110173093A1 (en) | 2007-11-14 | 2011-07-14 | Psota James Ryan | Evaluating public records of supply transactions for financial investment decisions | 
| US20110179048A1 (en) | 2001-02-20 | 2011-07-21 | Hartford Fire Insurance Company | Method and system for processing medical provider claim data | 
| US20110208565A1 (en) | 2010-02-23 | 2011-08-25 | Michael Ross | complex process management | 
| US20110225482A1 (en) | 2010-03-15 | 2011-09-15 | Wizpatent Pte Ltd | Managing and generating citations in scholarly work | 
| US20110258216A1 (en) | 2010-04-20 | 2011-10-20 | International Business Machines Corporation | Usability enhancements for bookmarks of browsers | 
| US8073857B2 (en) | 2009-02-17 | 2011-12-06 | International Business Machines Corporation | Semantics-based data transformation over a wire in mashups | 
| US20120004894A1 (en) | 2007-09-21 | 2012-01-05 | Edwin Brian Butler | Systems, Methods and Apparatuses for Generating and using Representations of Individual or Aggregate Human Medical Data | 
| US20120022945A1 (en) | 2010-07-22 | 2012-01-26 | Visa International Service Association | Systems and Methods to Identify Payment Accounts Having Business Spending Activities | 
| US8132149B2 (en) | 2005-03-14 | 2012-03-06 | Research In Motion Limited | System and method for applying development patterns for component based applications | 
| US20120059853A1 (en) | 2010-01-18 | 2012-03-08 | Salesforce.Com, Inc. | System and method of learning-based matching | 
| US20120084117A1 (en) | 2010-04-12 | 2012-04-05 | First Data Corporation | Transaction location analytics systems and methods | 
| US20120084184A1 (en) | 2008-12-18 | 2012-04-05 | Raleigh Gregory G | Enterprise Access Control and Accounting Allocation for Access Networks | 
| US20120123989A1 (en) | 2010-11-15 | 2012-05-17 | Business Objects Software Limited | Dashboard evaluator | 
| US20120137235A1 (en) | 2010-11-29 | 2012-05-31 | Sabarish T S | Dynamic user interface generation | 
| US20120191446A1 (en) | 2009-07-15 | 2012-07-26 | Proviciel - Mlstate | System and method for creating a parser generator and associated computer program | 
| US20120188252A1 (en) | 2007-01-31 | 2012-07-26 | Salesforce.Com Inc. | Method and system for presenting a visual representation of the portion of the sets of data that a query is expected to return | 
| US20120197657A1 (en) | 2011-01-31 | 2012-08-02 | Ez Derm, Llc | Systems and methods to facilitate medical services | 
| US20120197660A1 (en) | 2011-01-31 | 2012-08-02 | Ez Derm, Llc | Systems and methods to faciliate medical services | 
| US20120215784A1 (en) | 2007-03-20 | 2012-08-23 | Gary King | System for estimating a distribution of message content categories in source data | 
| US20120221553A1 (en) | 2011-02-24 | 2012-08-30 | Lexisnexis, A Division Of Reed Elsevier Inc. | Methods for electronic document searching and graphically representing electronic document searches | 
| US20120226590A1 (en) | 2011-03-01 | 2012-09-06 | Early Warning Services, Llc | System and method for suspect entity detection and mitigation | 
| US8271948B2 (en) | 2006-03-03 | 2012-09-18 | Telefonaktiebolaget L M Ericsson (Publ) | Subscriber identity module (SIM) application toolkit test method and system | 
| US8290838B1 (en) | 2006-12-29 | 2012-10-16 | Amazon Technologies, Inc. | Indicating irregularities in online financial transactions | 
| US8302855B2 (en) | 2005-03-09 | 2012-11-06 | Diebold, Incorporated | Banking system controlled responsive to data bearing records | 
| US20120284670A1 (en) | 2010-07-08 | 2012-11-08 | Alexey Kashik | Analysis of complex data objects and multiple parameter systems | 
| US20120304150A1 (en) | 2011-05-24 | 2012-11-29 | Microsoft Corporation | Binding between a layout engine and a scripting engine | 
| US20130016106A1 (en) | 2011-07-15 | 2013-01-17 | Green Charge Networks Llc | Cluster mapping to highlight areas of electrical congestion | 
| US20130024268A1 (en) | 2011-07-22 | 2013-01-24 | Ebay Inc. | Incentivizing the linking of internet content to products for sale | 
| US20130086482A1 (en) | 2011-09-30 | 2013-04-04 | Cbs Interactive, Inc. | Displaying plurality of content items in window | 
| US20130091084A1 (en) | 2011-10-11 | 2013-04-11 | Lockheed Martin Corporation | Data quality issue detection through ontological inferencing | 
| US20130124193A1 (en) | 2011-11-15 | 2013-05-16 | Business Objects Software Limited | System and Method Implementing a Text Analysis Service | 
| US20130151305A1 (en) | 2011-12-09 | 2013-06-13 | Sap Ag | Method and Apparatus for Business Drivers and Outcomes to Enable Scenario Planning and Simulation | 
| US20130151453A1 (en) | 2011-12-07 | 2013-06-13 | Inkiru, Inc. | Real-time predictive intelligence platform | 
| US20130166480A1 (en) | 2011-12-21 | 2013-06-27 | Telenav, Inc. | Navigation system with point of interest classification mechanism and method of operation thereof | 
| US20130225212A1 (en) | 2012-02-23 | 2013-08-29 | Research In Motion Corporation | Tagging instant message content for retrieval using mobile communication devices | 
| US20130251233A1 (en) | 2010-11-26 | 2013-09-26 | Guoliang Yang | Method for creating a report from radiological images using electronic report templates | 
| US8560494B1 (en) | 2011-09-30 | 2013-10-15 | Palantir Technologies, Inc. | Visual data importer | 
| US20140047319A1 (en) | 2012-08-13 | 2014-02-13 | Sap Ag | Context injection and extraction in xml documents based on common sparse templates | 
| US8682696B1 (en) | 2007-11-30 | 2014-03-25 | Intuit Inc. | Healthcare claims navigator | 
| US8688573B1 (en) | 2012-10-16 | 2014-04-01 | Intuit Inc. | Method and system for identifying a merchant payee associated with a cash transaction | 
| CN102054015B (en) | 2009-10-28 | 2014-05-07 | 财团法人工业技术研究院 | System and method for organizing community intelligence information using an organic object data model | 
| US20140129936A1 (en) | 2012-11-05 | 2014-05-08 | Palantir Technologies, Inc. | System and method for sharing investigation results | 
| US8732574B2 (en) | 2011-08-25 | 2014-05-20 | Palantir Technologies, Inc. | System and method for parameterizing documents for automatic workflow generation | 
| US20140208281A1 (en) | 2013-01-20 | 2014-07-24 | International Business Machines Corporation | Real-time display of electronic device design changes between schematic and/or physical representation and simplified physical representation of design | 
| US20140222793A1 (en) | 2013-02-07 | 2014-08-07 | Parlance Corporation | System and Method for Automatically Importing, Refreshing, Maintaining, and Merging Contact Sets | 
| US8807948B2 (en) | 2011-09-29 | 2014-08-19 | Cadence Design Systems, Inc. | System and method for automated real-time design checking | 
| US20140244284A1 (en) | 2013-02-25 | 2014-08-28 | Complete Consent, Llc | Communication of medical claims | 
| US20140244388A1 (en) | 2013-02-28 | 2014-08-28 | MetroStar Systems, Inc. | Social Content Synchronization | 
| EP2778914A1 (en) | 2013-03-15 | 2014-09-17 | Palantir Technologies, Inc. | Method and system for generating a parser and parsing complex data | 
| EP2778986A1 (en) | 2013-03-15 | 2014-09-17 | Palantir Technologies, Inc. | Systems and methods for providing a tagging interface for external content | 
| EP2778913A1 (en) | 2013-03-15 | 2014-09-17 | Palantir Technologies, Inc. | Method and system for generating a parser and parsing complex data | 
| DE102014204840A1 (en) | 2013-03-15 | 2014-09-18 | Palantir Technologies, Inc. | Improved data integration tool | 
| US20140358829A1 (en) | 2013-06-01 | 2014-12-04 | Adam M. Hurwitz | System and method for sharing record linkage information | 
| US8930874B2 (en) | 2012-11-09 | 2015-01-06 | Analog Devices, Inc. | Filter design tool | 
| US8930897B2 (en) | 2013-03-15 | 2015-01-06 | Palantir Technologies Inc. | Data integration tool | 
| US8938686B1 (en) | 2013-10-03 | 2015-01-20 | Palantir Technologies Inc. | Systems and methods for analyzing performance of an entity | 
| US20150026622A1 (en) | 2013-07-19 | 2015-01-22 | General Electric Company | Systems and methods for dynamically controlling content displayed on a condition monitoring system | 
| DE102014215621A1 (en) | 2013-08-08 | 2015-02-12 | Palantir Technologies, Inc. | Template system for generating customized documents | 
| US20150073954A1 (en) | 2012-12-06 | 2015-03-12 | Jpmorgan Chase Bank, N.A. | System and Method for Data Analytics | 
| US20150089353A1 (en) | 2013-09-24 | 2015-03-26 | Chad Folkening | Platform for building virtual entities using equity systems | 
| US9009827B1 (en) | 2014-02-20 | 2015-04-14 | Palantir Technologies Inc. | Security sharing system | 
| US20150106379A1 (en) | 2013-03-15 | 2015-04-16 | Palantir Technologies Inc. | Computer-implemented systems and methods for comparing and associating objects | 
| US20150212663A1 (en) | 2014-01-30 | 2015-07-30 | Splunk Inc. | Panel templates for visualization of data within an interactive dashboard | 
| US20150261847A1 (en) | 2012-10-22 | 2015-09-17 | Palantir Technologies, Inc. | Sharing information between nexuses that use different classification schemes for information access control | 
| US9165100B2 (en) | 2013-12-05 | 2015-10-20 | Honeywell International Inc. | Methods and apparatus to map schematic elements into a database | 
| US9223773B2 (en) | 2013-08-08 | 2015-12-29 | Palatir Technologies Inc. | Template system for custom document generation | 
| US20160062555A1 (en) | 2014-09-03 | 2016-03-03 | Palantir Technologies Inc. | System for providing dynamic linked panels in user interface | 
Family Cites Families (28)
| Publication number | Priority date | Publication date | Assignee | Title | 
|---|---|---|---|---|
| JP2626465B2 (en) * | 1993-04-27 | 1997-07-02 | 村田機械株式会社 | Diagnostic method and device for yarn monitor | 
| US5454106A (en) * | 1993-05-17 | 1995-09-26 | International Business Machines Corporation | Database retrieval system using natural language for presenting understood components of an ambiguous query on a user interface | 
| US5903756A (en) * | 1996-10-11 | 1999-05-11 | Sun Microsystems, Incorporated | Variable lookahead parser generator | 
| JP3497348B2 (en) | 1997-06-20 | 2004-02-16 | 株式会社日立製作所 | Production planning system | 
| US6236994B1 (en) * | 1997-10-21 | 2001-05-22 | Xerox Corporation | Method and apparatus for the integration of information and knowledge | 
| US6792435B1 (en) * | 1998-03-10 | 2004-09-14 | International Business Machines Corporation | Method and apparatus for recovering the definitions of dropped database objects | 
| US20050160401A1 (en) * | 1999-10-16 | 2005-07-21 | Computer Associates Think, Inc. | System and method for adding user-defined objects to a modeling tool | 
| US8707185B2 (en) | 2000-10-10 | 2014-04-22 | Addnclick, Inc. | Dynamic information management system and method for content delivery and sharing in content-, metadata- and viewer-based, live social networking among users concurrently engaged in the same and/or similar content | 
| US7519589B2 (en) * | 2003-02-04 | 2009-04-14 | Cataphora, Inc. | Method and apparatus for sociological data analysis | 
| US20040126840A1 (en) * | 2002-12-23 | 2004-07-01 | Affymetrix, Inc. | Method, system and computer software for providing genomic ontological data | 
| US20060278163A1 (en) | 2002-08-27 | 2006-12-14 | Ovshinsky Stanford R | High throughput deposition apparatus with magnetic support | 
| US7640267B2 (en) * | 2002-11-20 | 2009-12-29 | Radar Networks, Inc. | Methods and systems for managing entities in a computing device using semantic objects | 
| US10025588B1 (en) * | 2002-11-25 | 2018-07-17 | Teradata Us, Inc. | Parsing of database queries containing clauses specifying methods of user-defined data types | 
| US20040243531A1 (en) * | 2003-04-28 | 2004-12-02 | Dean Michael Anthony | Methods and systems for representing, using and displaying time-varying information on the Semantic Web | 
| US7496569B2 (en) * | 2003-08-29 | 2009-02-24 | Sap Ag | Database access statement parser | 
| US7712088B2 (en) * | 2004-07-08 | 2010-05-04 | Microsoft Corporation | Method and system for a batch parser | 
| US7328209B2 (en) * | 2004-08-11 | 2008-02-05 | Oracle International Corporation | System for ontology-based semantic matching in a relational database system | 
| US20060036633A1 (en) * | 2004-08-11 | 2006-02-16 | Oracle International Corporation | System for indexing ontology-based semantic matching operators in a relational database system | 
| US20060212474A1 (en) * | 2005-03-16 | 2006-09-21 | Muzzy Lane Software Incorporated | Specifying application content using data-driven systems | 
| US8117300B2 (en) * | 2005-04-25 | 2012-02-14 | Invensys Systems, Inc | Supporting both asynchronous and synchronous data transfers between production event information sources and a production information database | 
| US8020110B2 (en) * | 2005-05-26 | 2011-09-13 | Weisermazars Llp | Methods for defining queries, generating query results and displaying same | 
| US7552117B2 (en) * | 2005-05-26 | 2009-06-23 | International Business Machines Corporation | Using ontological relationships in a computer database | 
| US8417537B2 (en) | 2006-11-01 | 2013-04-09 | Microsoft Corporation | Extensible and localizable health-related dictionary | 
| US8135730B2 (en) * | 2009-06-09 | 2012-03-13 | International Business Machines Corporation | Ontology-based searching in database systems | 
| US8775226B2 (en) | 2011-08-29 | 2014-07-08 | International Business Machines Corporation | Computing and managing conflicting functional data requirements using ontologies | 
| US8880420B2 (en) | 2011-12-27 | 2014-11-04 | Grubhub, Inc. | Utility for creating heatmaps for the study of competitive advantage in the restaurant marketplace | 
| US10803106B1 (en) | 2015-02-24 | 2020-10-13 | Palantir Technologies Inc. | System with methodology for dynamic modular ontology | 
| US10248722B2 (en) | 2016-02-22 | 2019-04-02 | Palantir Technologies Inc. | Multi-language support for dynamic ontology | 
- 
        2006
        - 2006-11-20 US US11/602,626 patent/US7962495B2/en active Active
 
- 
        2007
        - 2007-11-20 EP EP18200807.8A patent/EP3462304B1/en active Active
- 2007-11-20 HU HUE07864644A patent/HUE041455T2/en unknown
- 2007-11-20 PL PL07864644T patent/PL2084597T3/en unknown
- 2007-11-20 SI SI200732068T patent/SI2084597T1/en unknown
- 2007-11-20 LT LTEP07864644.5T patent/LT2084597T/en unknown
- 2007-11-20 EP EP20191633.5A patent/EP3835968B8/en active Active
- 2007-11-20 DK DK07864644.5T patent/DK2084597T3/en active
- 2007-11-20 PT PT07864644T patent/PT2084597T/en unknown
- 2007-11-20 ES ES07864644T patent/ES2702611T3/en active Active
- 2007-11-20 AU AU2007323689A patent/AU2007323689B2/en not_active Ceased
- 2007-11-20 EP EP07864644.5A patent/EP2084597B1/en active Active
- 2007-11-20 WO PCT/US2007/085202 patent/WO2008064207A2/en not_active Ceased
- 2007-11-20 TR TR2019/00500T patent/TR201900500T4/en unknown
- 2007-11-20 CA CA2666364A patent/CA2666364C/en not_active Expired - Fee Related
 
- 
        2009
        - 2009-04-21 IL IL198253A patent/IL198253A/en active IP Right Grant
 
- 
        2011
        - 2011-05-12 US US13/106,636 patent/US8489623B2/en active Active
 
- 
        2013
        - 2013-06-12 US US13/916,447 patent/US8856153B2/en active Active
 
- 
        2014
        - 2014-10-07 US US14/508,696 patent/US9201920B2/en active Active
 
- 
        2015
        - 2015-11-30 US US14/954,680 patent/US9589014B2/en active Active
 
- 
        2017
        - 2017-03-02 US US15/448,491 patent/US10872067B2/en active Active
 
- 
        2020
        - 2020-12-15 US US17/123,019 patent/US11714792B2/en active Active
 
- 
        2023
        - 2023-06-16 US US18/336,876 patent/US12386803B2/en active Active
 
Patent Citations (248)
| Publication number | Priority date | Publication date | Assignee | Title | 
|---|---|---|---|---|
| US5241625A (en) | 1990-11-27 | 1993-08-31 | Farallon Computing, Inc. | Screen image sharing among heterogeneous computers | 
| US5999911A (en) | 1995-06-02 | 1999-12-07 | Mentor Graphics Corporation | Method and system for managing workflow | 
| US6539538B1 (en) | 1995-11-13 | 2003-03-25 | Concerto Software, Inc. | Intelligent information routing system and method | 
| US5845300A (en) | 1996-06-05 | 1998-12-01 | Microsoft Corporation | Method and apparatus for suggesting completions for a partially entered data item based on previously-entered, associated data items | 
| US6237138B1 (en) | 1996-11-12 | 2001-05-22 | International Business Machines Corp. | Buffered screen capturing software tool for usability testing of computer applications | 
| US6430305B1 (en) | 1996-12-20 | 2002-08-06 | Synaptics, Incorporated | Identity verification methods | 
| US6065026A (en) | 1997-01-09 | 2000-05-16 | Document.Com, Inc. | Multi-user electronic document authoring system with prompted updating of shared language | 
| US6463404B1 (en) | 1997-08-08 | 2002-10-08 | British Telecommunications Public Limited Company | Translation | 
| US6289338B1 (en) | 1997-12-15 | 2001-09-11 | Manning & Napier Information Services | Database analysis using a probabilistic ontology | 
| US6877137B1 (en) | 1998-04-09 | 2005-04-05 | Rose Blush Software Llc | System, method and computer program product for mediating notes and note sub-notes linked or otherwise associated with stored or networked web pages | 
| US6243706B1 (en) | 1998-07-24 | 2001-06-05 | Avid Technology, Inc. | System and method for managing the creation and production of computer generated works | 
| US6232971B1 (en) | 1998-09-23 | 2001-05-15 | International Business Machines Corporation | Variable modality child windows | 
| US7392254B1 (en) | 1998-10-16 | 2008-06-24 | Jenkins Steven R | Web-enabled transaction and matter management system | 
| US20070168871A1 (en) | 1998-10-16 | 2007-07-19 | Haynes And Boone, L.L.P. | Web-enabled transaction and collaborative management system | 
| US7213030B1 (en) | 1998-10-16 | 2007-05-01 | Jenkins Steven R | Web-enabled transaction and collaborative management system | 
| US6523172B1 (en) * | 1998-12-17 | 2003-02-18 | Evolutionary Technologies International, Inc. | Parser translator system and method | 
| US6748481B1 (en) | 1999-04-06 | 2004-06-08 | Microsoft Corporation | Streaming information appliance with circular buffer for receiving and selectively reading blocks of streaming information | 
| US20050028094A1 (en) | 1999-07-30 | 2005-02-03 | Microsoft Corporation | Modeless child windows for application programs | 
| US6523019B1 (en) | 1999-09-21 | 2003-02-18 | Choicemaker Technologies, Inc. | Probabilistic record linkage model derived from training data | 
| US20030126102A1 (en) | 1999-09-21 | 2003-07-03 | Choicemaker Technologies, Inc. | Probabilistic record linkage model derived from training data | 
| WO2001025906A1 (en) | 1999-10-01 | 2001-04-12 | Global Graphics Software Limited | Method and system for arranging a workflow using graphical user interface | 
| US20070185850A1 (en) | 1999-11-10 | 2007-08-09 | Walters Edward J | Apparatus and Method for Displaying Records Responsive to a Database Query | 
| US6370538B1 (en) | 1999-11-22 | 2002-04-09 | Xerox Corporation | Direct manipulation interface for document properties | 
| US6944821B1 (en) | 1999-12-07 | 2005-09-13 | International Business Machines Corporation | Copy/paste mechanism and paste buffer that includes source information for copied data | 
| US7194680B1 (en) | 1999-12-07 | 2007-03-20 | Adobe Systems Incorporated | Formatting content by example | 
| US20020032677A1 (en) | 2000-03-01 | 2002-03-14 | Jeff Morgenthaler | Methods for creating, editing, and updating searchable graphical database and databases of graphical images and information and displaying graphical images from a searchable graphical database or databases in a sequential or slide show format | 
| WO2001088750A1 (en) | 2000-05-16 | 2001-11-22 | Carroll Garrett O | A document processing system and method | 
| US20030093755A1 (en) | 2000-05-16 | 2003-05-15 | O'carroll Garrett | Document processing system and method | 
| US20070113164A1 (en) | 2000-05-17 | 2007-05-17 | Hansen David R | System and method for implementing compound documents in a production printing workflow | 
| US6967589B1 (en) | 2000-08-11 | 2005-11-22 | Oleumtech Corporation | Gas/oil well monitoring system | 
| GB2366498A (en) | 2000-08-25 | 2002-03-06 | Copyn Ltd | Method of bookmarking a section of a web-page and storing said bookmarks | 
| US6640231B1 (en) | 2000-10-06 | 2003-10-28 | Ontology Works, Inc. | Ontology for database design and application development | 
| WO2002035376A3 (en) | 2000-10-27 | 2003-08-28 | Science Applic Int Corp | Ontology-based parser for natural language processing | 
| US7027974B1 (en) | 2000-10-27 | 2006-04-11 | Science Applications International Corporation | Ontology-based parser for natural language processing | 
| US20040236688A1 (en) | 2000-10-30 | 2004-11-25 | Bozeman William O. | Universal positive pay database method, system, and computer useable medium | 
| US20020103705A1 (en) | 2000-12-06 | 2002-08-01 | Forecourt Communication Group | Method and apparatus for using prior purchases to select activities to present to a customer | 
| US20020095360A1 (en) | 2001-01-16 | 2002-07-18 | Joao Raymond Anthony | Apparatus and method for providing transaction history information, account history information, and/or charge-back information | 
| US6850317B2 (en) | 2001-01-23 | 2005-02-01 | Schlumberger Technology Corporation | Apparatus and methods for determining velocity of oil in a flow stream | 
| US8799313B2 (en) | 2001-02-20 | 2014-08-05 | Hartford Fire Insurance Company | Method and system for processing medical provider claim data | 
| US20110179048A1 (en) | 2001-02-20 | 2011-07-21 | Hartford Fire Insurance Company | Method and system for processing medical provider claim data | 
| US20100057622A1 (en) | 2001-02-27 | 2010-03-04 | Faith Patrick L | Distributed Quantum Encrypted Pattern Generation And Scoring | 
| US7877421B2 (en) | 2001-05-25 | 2011-01-25 | International Business Machines Corporation | Method and system for mapping enterprise data assets to a semantic information model | 
| US20020194201A1 (en) * | 2001-06-05 | 2002-12-19 | Wilbanks John Thompson | Systems, methods and computer program products for integrating biological/chemical databases to create an ontology network | 
| US6665683B1 (en) | 2001-06-22 | 2003-12-16 | E. Intelligence, Inc. | System and method for adjusting a value within a multidimensional aggregation tree | 
| US20020196229A1 (en) | 2001-06-26 | 2002-12-26 | Frank Chen | Graphics-based calculator capable of directly editing data points on graph | 
| US20040205492A1 (en) | 2001-07-26 | 2004-10-14 | Newsome Mark R. | Content clipping service | 
| US20030036927A1 (en) | 2001-08-20 | 2003-02-20 | Bowen Susan W. | Healthcare information search system and user interface | 
| US7089541B2 (en) | 2001-11-30 | 2006-08-08 | Sun Microsystems, Inc. | Modular parser architecture with mini parsers | 
| WO2003060751A1 (en) | 2001-12-26 | 2003-07-24 | Compassoft, Inc. | System and method for autonomously generating heterogeneous data source interoperability bridges based on semantic modeling derived from self adapting ontology | 
| US7174377B2 (en) | 2002-01-16 | 2007-02-06 | Xerox Corporation | Method and apparatus for collaborative document versioning of networked documents | 
| US20030177112A1 (en) * | 2002-01-28 | 2003-09-18 | Steve Gardner | Ontology-based information management system and method | 
| US7533069B2 (en) | 2002-02-01 | 2009-05-12 | John Fairweather | System and method for mining data | 
| US20070112714A1 (en) | 2002-02-01 | 2007-05-17 | John Fairweather | System and method for managing knowledge | 
| US7685083B2 (en) | 2002-02-01 | 2010-03-23 | John Fairweather | System and method for managing knowledge | 
| US7240330B2 (en) | 2002-02-01 | 2007-07-03 | John Fairweather | Use of ontologies for auto-generating and handling applications, their persistent storage, and user interfaces | 
| US20030172053A1 (en) | 2002-02-01 | 2003-09-11 | John Fairweather | System and method for mining data | 
| US20080249820A1 (en) | 2002-02-15 | 2008-10-09 | Pathria Anu K | Consistency modeling of healthcare claims to detect fraud and abuse | 
| US20040034570A1 (en) | 2002-03-20 | 2004-02-19 | Mark Davis | Targeted incentives based upon predicted behavior | 
| US7237192B1 (en) | 2002-04-30 | 2007-06-26 | Oracle International Corporation | Methods and systems for naming and indexing children in a hierarchical nodal structure | 
| US20090281839A1 (en) | 2002-05-17 | 2009-11-12 | Lawrence A. Lynn | Patient safety processor | 
| US20040044648A1 (en) | 2002-06-24 | 2004-03-04 | Xmyphonic System As | Method for data-centric collaboration | 
| US20060155654A1 (en) | 2002-08-13 | 2006-07-13 | Frederic Plessis | Editor and method for editing formulae for calculating the price of a service and a system for automatic costing of a service | 
| US20040044992A1 (en) | 2002-09-03 | 2004-03-04 | Horst Muller | Handling parameters in test scripts for computer program applications | 
| US20060178915A1 (en) | 2002-10-18 | 2006-08-10 | Schumarry Chao | Mass customization for management of healthcare | 
| US20040083466A1 (en) * | 2002-10-29 | 2004-04-29 | Dapp Michael C. | Hardware parser accelerator | 
| US20060123027A1 (en) * | 2003-02-10 | 2006-06-08 | Joern Kohlhammer | Time-critical filtering of information using domain ontologies | 
| US7086028B1 (en) | 2003-04-09 | 2006-08-01 | Autodesk, Inc. | Simplified generation of design change information on a drawing in a computer aided design (CAD) environment | 
| US20040221223A1 (en) | 2003-04-29 | 2004-11-04 | Nam-Yul Yu | Apparatus and method for encoding a low density parity check code | 
| US20040236711A1 (en) | 2003-05-21 | 2004-11-25 | Bentley Systems, Inc. | System and method for automating the extraction of information contained within an engineering document | 
| US7441219B2 (en) | 2003-06-24 | 2008-10-21 | National Semiconductor Corporation | Method for creating, modifying, and simulating electrical circuits over the internet | 
| US20050010472A1 (en) | 2003-07-08 | 2005-01-13 | Quatse Jesse T. | High-precision customer-based targeting by individual usage statistics | 
| US20050039116A1 (en) | 2003-07-31 | 2005-02-17 | Canon Kabushiki Kaisha | Collaborative editing with automatic layout | 
| US20050039119A1 (en) | 2003-08-12 | 2005-02-17 | Accenture Global Services Gmbh | Presentation generator | 
| US20060143075A1 (en) | 2003-09-22 | 2006-06-29 | Ryan Carr | Assumed demographics, predicted behaviour, and targeted incentives | 
| US7441182B2 (en) | 2003-10-23 | 2008-10-21 | Microsoft Corporation | Digital negatives | 
| US20050091186A1 (en) | 2003-10-24 | 2005-04-28 | Alon Elish | Integrated method and apparatus for capture, storage, and retrieval of information | 
| US20050091420A1 (en) | 2003-10-24 | 2005-04-28 | Microsoft Corporation | Mechanism for handling input parameters | 
| US20050125715A1 (en) | 2003-12-04 | 2005-06-09 | Fabrizio Di Franco | Method of saving data in a graphical user interface | 
| US20080228467A1 (en) | 2004-01-06 | 2008-09-18 | Neuric Technologies, Llc | Natural language parsing method to provide conceptual flow | 
| US20050183005A1 (en) | 2004-02-12 | 2005-08-18 | Laurent Denoue | Systems and methods for freeform annotations | 
| US20060053097A1 (en) | 2004-04-01 | 2006-03-09 | King Martin T | Searching and accessing documents on private networks for use with captures from rendered documents | 
| US20060031779A1 (en) | 2004-04-15 | 2006-02-09 | Citrix Systems, Inc. | Selectively sharing screen data | 
| US20060265417A1 (en) | 2004-05-04 | 2006-11-23 | Amato Jerry S | Enhanced graphical interfaces for displaying visual data | 
| US20100223260A1 (en) | 2004-05-06 | 2010-09-02 | Oracle International Corporation | Web Server for Multi-Version Web Documents | 
| US20090172821A1 (en) | 2004-06-30 | 2009-07-02 | Faycal Daira | System and method for securing computer stations and/or communication networks | 
| US20060026561A1 (en) | 2004-07-29 | 2006-02-02 | International Business Machines Corporation | Inserting into a document a screen image of a computer software application | 
| US20100204983A1 (en) | 2004-08-06 | 2010-08-12 | Kevin Chen-Chuan Chung | Method and System for Extracting Web Query Interfaces | 
| US20060053170A1 (en) | 2004-09-03 | 2006-03-09 | Bio Wisdom Limited | System and method for parsing and/or exporting data from one or more multi-relational ontologies | 
| US20060059423A1 (en) | 2004-09-13 | 2006-03-16 | Stefan Lehmann | Apparatus, system, and method for creating customized workflow documentation | 
| US20060080139A1 (en) | 2004-10-08 | 2006-04-13 | Woodhaven Health Services | Preadmission health care cost and reimbursement estimation tool | 
| US20070299697A1 (en) | 2004-10-12 | 2007-12-27 | Friedlander Robert R | Methods for Associating Records in Healthcare Databases with Individuals | 
| US20060129746A1 (en) | 2004-12-14 | 2006-06-15 | Ithink, Inc. | Method and graphic interface for storing, moving, sending or printing electronic data to two or more locations, in two or more formats with a single save function | 
| EP1672527A2 (en) | 2004-12-15 | 2006-06-21 | Microsoft Corporation | System and method for automatically completing spreadsheet formulas | 
| US20060136513A1 (en) | 2004-12-21 | 2006-06-22 | Nextpage, Inc. | Managing the status of documents in a distributed storage system | 
| US20100280851A1 (en) | 2005-02-22 | 2010-11-04 | Richard Merkin | Systems and methods for assessing and optimizing healthcare administration | 
| US8302855B2 (en) | 2005-03-09 | 2012-11-06 | Diebold, Incorporated | Banking system controlled responsive to data bearing records | 
| US8132149B2 (en) | 2005-03-14 | 2012-03-06 | Research In Motion Limited | System and method for applying development patterns for component based applications | 
| US20060218163A1 (en) | 2005-03-28 | 2006-09-28 | Microsoft Corporation | Rapid prototyping database | 
| US20100262901A1 (en) | 2005-04-14 | 2010-10-14 | Disalvo Dean F | Engineering process for a real-time user-defined data collection, analysis, and optimization tool (dot) | 
| US20060277460A1 (en) | 2005-06-03 | 2006-12-07 | Scott Forstall | Webview applications | 
| US20070000999A1 (en) | 2005-06-06 | 2007-01-04 | First Data Corporation | System and method for authorizing electronic payment transactions | 
| US20070043686A1 (en) | 2005-08-22 | 2007-02-22 | International Business Machines Corporation | Xml sub-document versioning method in xml databases using record storages | 
| US20070074169A1 (en) | 2005-08-25 | 2007-03-29 | Fortify Software, Inc. | Apparatus and method for analyzing and supplementing a program to provide security | 
| US7958147B1 (en) | 2005-09-13 | 2011-06-07 | James Luke Turner | Method for providing customized and automated security assistance, a document marking regime, and central tracking and control for sensitive or classified documents in electronic format | 
| US7941336B1 (en) | 2005-09-14 | 2011-05-10 | D2C Solutions, LLC | Segregation-of-duties analysis apparatus and method | 
| US20070061752A1 (en) | 2005-09-15 | 2007-03-15 | Microsoft Corporation | Cross-application support of charts | 
| US20070078872A1 (en) | 2005-09-30 | 2007-04-05 | Ronen Cohen | Apparatus and method for parsing unstructured data | 
| US20090313463A1 (en) | 2005-11-01 | 2009-12-17 | Commonwealth Scientific And Industrial Research Organisation | Data matching using data clusters | 
| US20070136095A1 (en) | 2005-12-09 | 2007-06-14 | Arizona Board Of Regents On Behalf Of The University Of Arizona | Icon Queues for Workflow Management | 
| US8271948B2 (en) | 2006-03-03 | 2012-09-18 | Telefonaktiebolaget L M Ericsson (Publ) | Subscriber identity module (SIM) application toolkit test method and system | 
| US20070233709A1 (en) | 2006-03-30 | 2007-10-04 | Emc Corporation | Smart containers | 
| US20070245339A1 (en) | 2006-04-12 | 2007-10-18 | Bauman Brian D | Creating documentation screenshots on demand | 
| WO2007133206A1 (en) | 2006-05-12 | 2007-11-22 | Drawing Management Incorporated | Spatial graphical user interface and method for using the same | 
| US20070284433A1 (en) | 2006-06-08 | 2007-12-13 | American Express Travel Related Services Company, Inc. | Method, system, and computer program product for customer-level data verification | 
| US20080016155A1 (en) | 2006-07-11 | 2008-01-17 | Igor Khalatian | One-Click Universal Screen Sharing | 
| US20080091693A1 (en) | 2006-10-16 | 2008-04-17 | Oracle International Corporation | Managing compound XML documents in a repository | 
| US20080148398A1 (en) | 2006-10-31 | 2008-06-19 | Derek John Mezack | System and Method for Definition and Automated Analysis of Computer Security Threat Models | 
| US20080109714A1 (en) | 2006-11-03 | 2008-05-08 | Sap Ag | Capturing screen information | 
| US20130275446A1 (en) | 2006-11-20 | 2013-10-17 | Palantir Technologies, Inc. | Creating data in a data store using a dynamic ontology | 
| US8489623B2 (en) | 2006-11-20 | 2013-07-16 | Palantir Technologies, Inc. | Creating data in a data store using a dynamic ontology | 
| US7962495B2 (en) | 2006-11-20 | 2011-06-14 | Palantir Technologies, Inc. | Creating data in a data store using a dynamic ontology | 
| WO2008064207A2 (en) | 2006-11-20 | 2008-05-29 | Palantir Technologies, Inc. | Creating data in a data store using a dynamic ontology | 
| CA2666364C (en) | 2006-11-20 | 2015-01-06 | Palantir Technologies, Inc. | Creating data in a data store using a dynamic ontology | 
| US20150142766A1 (en) | 2006-11-20 | 2015-05-21 | Palantir Technologies, Inc. | Creating Data in a Data Store Using a Dynamic Ontology | 
| US9201920B2 (en) | 2006-11-20 | 2015-12-01 | Palantir Technologies, Inc. | Creating data in a data store using a dynamic ontology | 
| IL198253A (en) | 2006-11-20 | 2016-06-30 | Palantir Technologies Inc | Creating data in a data store using a dynamic ontology | 
| US20080140387A1 (en) | 2006-12-07 | 2008-06-12 | Linker Sheldon O | Method and system for machine understanding, knowledge, and conversation | 
| US8117022B2 (en) | 2006-12-07 | 2012-02-14 | Linker Sheldon O | Method and system for machine understanding, knowledge, and conversation | 
| US8290838B1 (en) | 2006-12-29 | 2012-10-16 | Amazon Technologies, Inc. | Indicating irregularities in online financial transactions | 
| US20080177782A1 (en) | 2007-01-10 | 2008-07-24 | Pado Metaware Ab | Method and system for facilitating the production of documents | 
| US20080172607A1 (en) | 2007-01-15 | 2008-07-17 | Microsoft Corporation | Selective Undo of Editing Operations Performed on Data Objects | 
| US20120188252A1 (en) | 2007-01-31 | 2012-07-26 | Salesforce.Com Inc. | Method and system for presenting a visual representation of the portion of the sets of data that a query is expected to return | 
| US20120215784A1 (en) | 2007-03-20 | 2012-08-23 | Gary King | System for estimating a distribution of message content categories in source data | 
| US20090031401A1 (en) | 2007-04-27 | 2009-01-29 | Bea Systems, Inc. | Annotations for enterprise web application constructor | 
| US7880921B2 (en) | 2007-05-01 | 2011-02-01 | Michael Joseph Dattilo | Method and apparatus to digitally whiteout mistakes on a printed form | 
| US20080281580A1 (en) | 2007-05-10 | 2008-11-13 | Microsoft Corporation | Dynamic parser | 
| US8010507B2 (en) | 2007-05-24 | 2011-08-30 | Pado Metaware Ab | Method and system for harmonization of variants of a sequential file | 
| US20080313243A1 (en) | 2007-05-24 | 2008-12-18 | Pado Metaware Ab | method and system for harmonization of variants of a sequential file | 
| US20080313132A1 (en) | 2007-06-15 | 2008-12-18 | Fang Hao | High accuracy bloom filter using partitioned hashing | 
| US7966199B1 (en) | 2007-07-19 | 2011-06-21 | Intuit Inc. | Method and system for identification of geographic condition zones using aggregated claim data | 
| US20090043801A1 (en) | 2007-08-06 | 2009-02-12 | Intuit Inc. | Method and apparatus for selecting a doctor based on an observed experience level | 
| US20120004894A1 (en) | 2007-09-21 | 2012-01-05 | Edwin Brian Butler | Systems, Methods and Apparatuses for Generating and using Representations of Individual or Aggregate Human Medical Data | 
| US20090089651A1 (en) | 2007-09-27 | 2009-04-02 | Tilman Herberger | System and method for dynamic content insertion from the internet into a multimedia work | 
| US20090106178A1 (en) | 2007-10-23 | 2009-04-23 | Sas Institute Inc. | Computer-Implemented Systems And Methods For Updating Predictive Models | 
| US20090112678A1 (en) | 2007-10-26 | 2009-04-30 | Ingram Micro Inc. | System and method for knowledge management | 
| US20090112745A1 (en) | 2007-10-30 | 2009-04-30 | Intuit Inc. | Technique for reducing phishing | 
| US20110173093A1 (en) | 2007-11-14 | 2011-07-14 | Psota James Ryan | Evaluating public records of supply transactions for financial investment decisions | 
| US8682696B1 (en) | 2007-11-30 | 2014-03-25 | Intuit Inc. | Healthcare claims navigator | 
| US20090150868A1 (en) | 2007-12-10 | 2009-06-11 | Al Chakra | Method and System for Capturing Movie Shots at the Time of an Automated Graphical User Interface Test Failure | 
| US20090177962A1 (en) | 2008-01-04 | 2009-07-09 | Microsoft Corporation | Intelligently representing files in a view | 
| US20090187546A1 (en) | 2008-01-21 | 2009-07-23 | International Business Machines Corporation | Method, System and Computer Program Product for Duplicate Detection | 
| US20090199106A1 (en) | 2008-02-05 | 2009-08-06 | Sony Ericsson Mobile Communications Ab | Communication terminal including graphical bookmark manager | 
| US7765489B1 (en) | 2008-03-03 | 2010-07-27 | Shah Shalin N | Presenting notifications related to a medical study on a toolbar | 
| US20090248757A1 (en) | 2008-04-01 | 2009-10-01 | Microsoft Corporation | Application-Managed File Versioning | 
| US20090249178A1 (en) | 2008-04-01 | 2009-10-01 | Ambrosino Timothy J | Document linking | 
| US20090254970A1 (en) | 2008-04-04 | 2009-10-08 | Avaya Inc. | Multi-tier security event correlation and mitigation | 
| US20090271343A1 (en) | 2008-04-25 | 2009-10-29 | Anthony Vaiciulis | Automated entity identification for efficient profiling in an event probability prediction system | 
| US20090282068A1 (en) | 2008-05-12 | 2009-11-12 | Shockro John J | Semantic packager | 
| US20110161409A1 (en) | 2008-06-02 | 2011-06-30 | Azuki Systems, Inc. | Media mashup system | 
| US20090307049A1 (en) | 2008-06-05 | 2009-12-10 | Fair Isaac Corporation | Soft Co-Clustering of Data | 
| US20090319891A1 (en) | 2008-06-22 | 2009-12-24 | Mackinlay Jock Douglas | Methods and systems of automatically generating marks in a graphical view | 
| US20100011282A1 (en) | 2008-07-11 | 2010-01-14 | iCyte Pty Ltd. | Annotation system and method | 
| US8984390B2 (en) | 2008-09-15 | 2015-03-17 | Palantir Technologies, Inc. | One-click sharing for screenshots and related documents | 
| US20100070844A1 (en) | 2008-09-15 | 2010-03-18 | Andrew Aymeloglu | Automatic creation and server push of drafts | 
| WO2010030913A2 (en) | 2008-09-15 | 2010-03-18 | Palantir Technologies, Inc. | Modal-less interface enhancements | 
| WO2010030914A3 (en) | 2008-09-15 | 2010-06-17 | Palantir Technologies, Inc. | One-click sharing for screenshots and related documents | 
| US20100098318A1 (en) | 2008-10-20 | 2010-04-22 | Jpmorgan Chase Bank, N.A. | Method and System for Duplicate Check Detection | 
| US20120084184A1 (en) | 2008-12-18 | 2012-04-05 | Raleigh Gregory G | Enterprise Access Control and Accounting Allocation for Access Networks | 
| US8073857B2 (en) | 2009-02-17 | 2011-12-06 | International Business Machines Corporation | Semantics-based data transformation over a wire in mashups | 
| EP2221725A1 (en) | 2009-02-19 | 2010-08-25 | Mecel Aktiebolag | Validator for validating conformity of a software configuration | 
| US20100238174A1 (en) | 2009-03-18 | 2010-09-23 | Andreas Peter Haub | Cursor Synchronization in a Plurality of Graphs | 
| US20100306285A1 (en) | 2009-05-28 | 2010-12-02 | Arcsight, Inc. | Specifying a Parser Using a Properties File | 
| US20100313119A1 (en) | 2009-06-05 | 2010-12-09 | Microsoft Corporation | In-line dynamic text with variable formatting | 
| US20100313239A1 (en) | 2009-06-09 | 2010-12-09 | International Business Machines Corporation | Automated access control for rendered output | 
| US20120191446A1 (en) | 2009-07-15 | 2012-07-26 | Proviciel - Mlstate | System and method for creating a parser generator and associated computer program | 
| US20110047540A1 (en) | 2009-08-24 | 2011-02-24 | Embarcadero Technologies Inc. | System and Methodology for Automating Delivery, Licensing, and Availability of Software Products | 
| US20110074788A1 (en) | 2009-09-30 | 2011-03-31 | Mckesson Financial Holdings Limited | Methods, apparatuses, and computer program products for facilitating visualization and analysis of medical data | 
| US20110093327A1 (en) | 2009-10-15 | 2011-04-21 | Visa U.S.A. Inc. | Systems and Methods to Match Identifiers | 
| CN102054015B (en) | 2009-10-28 | 2014-05-07 | 财团法人工业技术研究院 | System and method for organizing community intelligence information using an organic object data model | 
| US20110099133A1 (en) | 2009-10-28 | 2011-04-28 | Industrial Technology Research Institute | Systems and methods for capturing and managing collective social intelligence information | 
| WO2011071833A1 (en) | 2009-12-07 | 2011-06-16 | Accenture Global Services Gmbh | Method and system for accelerated data quality enhancement | 
| US20120059853A1 (en) | 2010-01-18 | 2012-03-08 | Salesforce.Com, Inc. | System and method of learning-based matching | 
| US20110208565A1 (en) | 2010-02-23 | 2011-08-25 | Michael Ross | complex process management | 
| US20110225482A1 (en) | 2010-03-15 | 2011-09-15 | Wizpatent Pte Ltd | Managing and generating citations in scholarly work | 
| US20120084117A1 (en) | 2010-04-12 | 2012-04-05 | First Data Corporation | Transaction location analytics systems and methods | 
| US20110258216A1 (en) | 2010-04-20 | 2011-10-20 | International Business Machines Corporation | Usability enhancements for bookmarks of browsers | 
| US20120284670A1 (en) | 2010-07-08 | 2012-11-08 | Alexey Kashik | Analysis of complex data objects and multiple parameter systems | 
| US20120022945A1 (en) | 2010-07-22 | 2012-01-26 | Visa International Service Association | Systems and Methods to Identify Payment Accounts Having Business Spending Activities | 
| US20120123989A1 (en) | 2010-11-15 | 2012-05-17 | Business Objects Software Limited | Dashboard evaluator | 
| US20130251233A1 (en) | 2010-11-26 | 2013-09-26 | Guoliang Yang | Method for creating a report from radiological images using electronic report templates | 
| US20120137235A1 (en) | 2010-11-29 | 2012-05-31 | Sabarish T S | Dynamic user interface generation | 
| US20120197660A1 (en) | 2011-01-31 | 2012-08-02 | Ez Derm, Llc | Systems and methods to faciliate medical services | 
| US20120197657A1 (en) | 2011-01-31 | 2012-08-02 | Ez Derm, Llc | Systems and methods to facilitate medical services | 
| US20120221553A1 (en) | 2011-02-24 | 2012-08-30 | Lexisnexis, A Division Of Reed Elsevier Inc. | Methods for electronic document searching and graphically representing electronic document searches | 
| WO2012119008A2 (en) | 2011-03-01 | 2012-09-07 | Early Warning Services, Llc | System and method for suspect entity detection and mitigation | 
| US20120226590A1 (en) | 2011-03-01 | 2012-09-06 | Early Warning Services, Llc | System and method for suspect entity detection and mitigation | 
| US8689182B2 (en) | 2011-05-24 | 2014-04-01 | Microsoft Corporation | Memory model for a layout engine and scripting engine | 
| US20120304150A1 (en) | 2011-05-24 | 2012-11-29 | Microsoft Corporation | Binding between a layout engine and a scripting engine | 
| US20130016106A1 (en) | 2011-07-15 | 2013-01-17 | Green Charge Networks Llc | Cluster mapping to highlight areas of electrical congestion | 
| US20130024268A1 (en) | 2011-07-22 | 2013-01-24 | Ebay Inc. | Incentivizing the linking of internet content to products for sale | 
| US9058315B2 (en) | 2011-08-25 | 2015-06-16 | Palantir Technologies, Inc. | System and method for parameterizing documents for automatic workflow generation | 
| US20150254220A1 (en) | 2011-08-25 | 2015-09-10 | Palantir Technologies, Inc. | System and method for parameterizing documents for automatic workflow generation | 
| US8732574B2 (en) | 2011-08-25 | 2014-05-20 | Palantir Technologies, Inc. | System and method for parameterizing documents for automatic workflow generation | 
| US8807948B2 (en) | 2011-09-29 | 2014-08-19 | Cadence Design Systems, Inc. | System and method for automated real-time design checking | 
| US8560494B1 (en) | 2011-09-30 | 2013-10-15 | Palantir Technologies, Inc. | Visual data importer | 
| US20130086482A1 (en) | 2011-09-30 | 2013-04-04 | Cbs Interactive, Inc. | Displaying plurality of content items in window | 
| US20130091084A1 (en) | 2011-10-11 | 2013-04-11 | Lockheed Martin Corporation | Data quality issue detection through ontological inferencing | 
| US20130124193A1 (en) | 2011-11-15 | 2013-05-16 | Business Objects Software Limited | System and Method Implementing a Text Analysis Service | 
| US20130151453A1 (en) | 2011-12-07 | 2013-06-13 | Inkiru, Inc. | Real-time predictive intelligence platform | 
| US20130151305A1 (en) | 2011-12-09 | 2013-06-13 | Sap Ag | Method and Apparatus for Business Drivers and Outcomes to Enable Scenario Planning and Simulation | 
| US20130166480A1 (en) | 2011-12-21 | 2013-06-27 | Telenav, Inc. | Navigation system with point of interest classification mechanism and method of operation thereof | 
| US20130225212A1 (en) | 2012-02-23 | 2013-08-29 | Research In Motion Corporation | Tagging instant message content for retrieval using mobile communication devices | 
| US20140047319A1 (en) | 2012-08-13 | 2014-02-13 | Sap Ag | Context injection and extraction in xml documents based on common sparse templates | 
| US8688573B1 (en) | 2012-10-16 | 2014-04-01 | Intuit Inc. | Method and system for identifying a merchant payee associated with a cash transaction | 
| US20150261847A1 (en) | 2012-10-22 | 2015-09-17 | Palantir Technologies, Inc. | Sharing information between nexuses that use different classification schemes for information access control | 
| US20140129936A1 (en) | 2012-11-05 | 2014-05-08 | Palantir Technologies, Inc. | System and method for sharing investigation results | 
| AU2013251186B2 (en) | 2012-11-05 | 2015-11-19 | Palantir Technologies, Inc. | System and Method for Sharing Investigation Result Data | 
| US8930874B2 (en) | 2012-11-09 | 2015-01-06 | Analog Devices, Inc. | Filter design tool | 
| US20150073954A1 (en) | 2012-12-06 | 2015-03-12 | Jpmorgan Chase Bank, N.A. | System and Method for Data Analytics | 
| US20140208281A1 (en) | 2013-01-20 | 2014-07-24 | International Business Machines Corporation | Real-time display of electronic device design changes between schematic and/or physical representation and simplified physical representation of design | 
| US20140222793A1 (en) | 2013-02-07 | 2014-08-07 | Parlance Corporation | System and Method for Automatically Importing, Refreshing, Maintaining, and Merging Contact Sets | 
| US20140244284A1 (en) | 2013-02-25 | 2014-08-28 | Complete Consent, Llc | Communication of medical claims | 
| US20140244388A1 (en) | 2013-02-28 | 2014-08-28 | MetroStar Systems, Inc. | Social Content Synchronization | 
| US20150106379A1 (en) | 2013-03-15 | 2015-04-16 | Palantir Technologies Inc. | Computer-implemented systems and methods for comparing and associating objects | 
| US8930897B2 (en) | 2013-03-15 | 2015-01-06 | Palantir Technologies Inc. | Data integration tool | 
| US20150046481A1 (en) | 2013-03-15 | 2015-02-12 | Palantir Technologies Inc. | Method and system for generating a parser and parsing complex data | 
| EP2778986A1 (en) | 2013-03-15 | 2014-09-17 | Palantir Technologies, Inc. | Systems and methods for providing a tagging interface for external content | 
| US8903717B2 (en) | 2013-03-15 | 2014-12-02 | Palantir Technologies Inc. | Method and system for generating a parser and parsing complex data | 
| GB2513007A (en) | 2013-03-15 | 2014-10-15 | Palantir Technologies Inc | Transformation of data items from data sources using a transformation script | 
| EP2778913A1 (en) | 2013-03-15 | 2014-09-17 | Palantir Technologies, Inc. | Method and system for generating a parser and parsing complex data | 
| DE102014204840A1 (en) | 2013-03-15 | 2014-09-18 | Palantir Technologies, Inc. | Improved data integration tool | 
| US20150100559A1 (en) | 2013-03-15 | 2015-04-09 | Palantir Technologies Inc. | Data integration tool | 
| EP2778914A1 (en) | 2013-03-15 | 2014-09-17 | Palantir Technologies, Inc. | Method and system for generating a parser and parsing complex data | 
| US8855999B1 (en) | 2013-03-15 | 2014-10-07 | Palantir Technologies Inc. | Method and system for generating a parser and parsing complex data | 
| US20140358829A1 (en) | 2013-06-01 | 2014-12-04 | Adam M. Hurwitz | System and method for sharing record linkage information | 
| US20150026622A1 (en) | 2013-07-19 | 2015-01-22 | General Electric Company | Systems and methods for dynamically controlling content displayed on a condition monitoring system | 
| NL2013306B1 (en) | 2013-08-08 | 2016-05-10 | Palantir Technologies Inc | Template System For Custom Document Generation. | 
| GB2518745A (en) | 2013-08-08 | 2015-04-01 | Palantir Technologies Inc | Template system for custom document generation | 
| DE102014215621A1 (en) | 2013-08-08 | 2015-02-12 | Palantir Technologies, Inc. | Template system for generating customized documents | 
| US9223773B2 (en) | 2013-08-08 | 2015-12-29 | Palatir Technologies Inc. | Template system for custom document generation | 
| US20150089353A1 (en) | 2013-09-24 | 2015-03-26 | Chad Folkening | Platform for building virtual entities using equity systems | 
| US8938686B1 (en) | 2013-10-03 | 2015-01-20 | Palantir Technologies Inc. | Systems and methods for analyzing performance of an entity | 
| US9165100B2 (en) | 2013-12-05 | 2015-10-20 | Honeywell International Inc. | Methods and apparatus to map schematic elements into a database | 
| US20150212663A1 (en) | 2014-01-30 | 2015-07-30 | Splunk Inc. | Panel templates for visualization of data within an interactive dashboard | 
| EP2911078A2 (en) | 2014-02-20 | 2015-08-26 | Palantir Technologies, Inc. | Security sharing system | 
| US9009827B1 (en) | 2014-02-20 | 2015-04-14 | Palantir Technologies Inc. | Security sharing system | 
| EP2993595A1 (en) | 2014-09-03 | 2016-03-09 | Palantir Technologies, Inc. | Dynamic user interface | 
| US20160062555A1 (en) | 2014-09-03 | 2016-03-03 | Palantir Technologies Inc. | System for providing dynamic linked panels in user interface | 
Non-Patent Citations (128)
| Title | 
|---|
| "A Tour of Pinboard," <http://pinboard.in/tour> as printed May 15, 2014 in 6 pages. | 
| "A Tour of Pinboard," as printed May 15, 2014 in 6 pages. | 
| "BackTult-JD Edwards One World Version Control System," printed Jul. 23, 2007 in 1 page. | 
| "GrabUp-What a Timesaver!" , Aug. 11, 2008, pp. 3. | 
| "GrabUp-What a Timesaver!" <http://atlchris.com/191/grabup/>, Aug. 11, 2008, pp. 3. | 
| Abbey, Kristen, "Review of Google Docs," May 1, 2007, pp. 2. | 
| Adams et al., "Worklets: A Service-Oriented Implementation of Dynamic Flexibility in Workflows," R. Meersman, Z. Tari et al. (Eds.): OTM 2006, LNCS, 4275, pp. 291-308, 2006. | 
| Bluttman et al., "Excel Formulas and Functions for Dummies," 2005, Wiley Publishing, Inc., pp. 280, 284-286. | 
| Chaudhuri et al., "An Overview of Business Intelligence Technology," Communications of the ACM, Aug. 2011, vol. 54, No. 8. | 
| Claims for European Patent Application No. 07864644.5 dated Jul. 2016, 4 pages. | 
| Claims for Israel Patent Application No. 198253 dated Jan. 2016, 8 pages. | 
| Conner, Nancy, "Google Apps: The Missing Manual," May 1, 2008, pp. 15. | 
| Davis, "Combining a Flexible Data Model and Phase Schema Translation in Data Model Reverse Engineering," dated 1996, IEEE, 12 pages. | 
| Delicious, <http://delicious.com/> as printed May 15, 2014 in 1 page. | 
| Delicious, as printed May 15, 2014 in 1 page. | 
| Galliford, Miles, "Snaglt Versus Free Screen Capture Software: Critical Tools for Website Owners," , Mar. 27, 2008, pp. 11. | 
| Galliford, Miles, "Snaglt Versus Free Screen Capture Software: Critical Tools for Website Owners," <http://www.subhub.com/articles/free-screen-capture-software>, Mar. 27, 2008, pp. 11. | 
| Geiger, Jonathan G., "Data Quality Management, the Most Critical Initiative You Can Implement," Data Warehousing, Management and Quality, Paper 098-29, SUGI 29, Intelligent Solutions, Inc., Bounder, CO, pp. 14, accessed Oct. 3, 2013. | 
| Gu et al., "Record Linkage: Current Practice and Future Directions," Jan. 15, 2004, pp. 32. | 
| Hua et al., "A Multi-attribute Data Structure with Parallel Bloom Filters for Network Services", HiPC 2006, LNCS 4297, pp. 277-288, 2006. | 
| JetScreenshot.com, "Share Screenshots via Internet in Seconds," , Aug. 7, 2013, pp. 1. | 
| JetScreenshot.com, "Share Screenshots via Internet in Seconds," <http://web.archive.org/web/20130807164204/http://www.jetscreenshot.com/>, Aug. 7, 2013, pp. 1. | 
| Kahan et al., "Annotea: an Open RDF Infastructure for Shared Web Annotations", Computer Networks, Elsevier Science Publishers B.V., vol. 39, No. 5, dated Aug. 5, 2002, pp. 589-608. | 
| Klemmer et al., "Where Do Web Sites Come From? Capturing and Interacting with Design History," Association for Computing Machinery, CHI 2002, Apr. 20-25, 2002, Minneapolis, MN, pp. 8. | 
| Kokossi et al., "D7-Dynamic Ontoloty Management System (Design)," Information Societies Technology Programme, Jan. 10, 2002, pp. 1-27. | 
| Maluf et al., "An Extenible Schema-Less Database Framework for Managing High-Throughpit Structured Documents," Proceedings of the lasted International Conference, dated May 21, 2003, pp. 225-230. | 
| Microsoft Windows, "Microsoft Windows Version 2002 Print Out 2," 2002, pp. 1-6. | 
| Microsoft, "Registering an Application to a URI Scheme," , printed Apr. 4, 2009 in 4 pages. | 
| Microsoft, "Registering an Application to a URI Scheme," <http://msdn.microsoft.com/en-us/library/aa767914.aspx>, printed Apr. 4, 2009 in 4 pages. | 
| Microsoft, "Using the Clipboard," , printed Jun. 8, 2009 in 20 pages. | 
| Microsoft, "Using the Clipboard," <http://msdn.microsoft.com/en-us/library/ms649016.aspx>, printed Jun. 8, 2009 in 20 pages. | 
| Miklau et al., "Securing History: Privacy and Accountability in Database Systems," 3rd Biennial Conference on Innovative Data Systems Research (CIDR), Jan. 7-10, 2007, Asilomar, California, pp. 387-396. | 
| Morrison et al., "Converting Users to Testers: An Alternative Approach to Load Test Script Creation, Parameterization and Data Corellation," CCSC: Southeastern Conference, JCSC 28, 2, Dec. 2012, pp. 188-196. | 
| Niepert et al., "A Dynamic Ontology for a Dynamic Reference Work", Joint Conference on Digital Libraries, Jun. 17-22, 2007, Vancouver, British Columbia, Canada, pp. 1-10. | 
| Nitro, "Trick: How to Capture a Screenshot As PDF, Annotate, Then Share It," <http://blog.nitropdf.com/2008/03/04/trick-how-to-capture-a-screenshot-as-pdf-annotate-it-then-share/>, Mar. 4, 2008, pp. 2. | 
| Nivas, Tuli, "Test Harness and Script Design Principles for Automated Testing of non-GUI or Web Based Applications," Performance Lab, Jun. 2011, pp. 30-37. | 
| Notice of Acceptance for Australian Patent Application No. 2013251186 dated Nov. 6, 2015. | 
| Official Communicaiton for European Patent Application No. 07864644.5 dated Jul. 12, 2016, 10 pages. | 
| Official Communication for Australian Patent Application No. 2013251186 dated Mar. 12, 2015. | 
| Official Communication for Australian Patent Application No. 2014201506 dated Feb. 27, 2015. | 
| Official Communication for Australian Patent Application No. 2014201507 dated Feb. 27, 2015. | 
| Official Communication for Australian Patent Application No. 2014201580 dated Feb. 27, 2015. | 
| Official Communication for Canadian Patent Application No. 2666364 dated Jun. 4, 2012. | 
| Official Communication for Canadian Patent Application No. 2831660 dated Jun. 9, 2015. | 
| Official Communication for European Patent Application No. 12181585.6 dated Sep. 4, 2015. | 
| Official Communication for European Patent Application No. 14158958.0 dated Apr. 16, 2015. | 
| Official Communication for European Patent Application No. 14158958.0 dated Jun. 3, 2014. | 
| Official Communication for European Patent Application No. 14158977.0 dated Apr. 16, 2015. | 
| Official Communication for European Patent Application No. 14158977.0 dated Jun. 10, 2014. | 
| Official Communication for European Patent Application No. 14159629.6 dated Jul. 31, 2014. | 
| Official Communication for European Patent Application No. 15155845.9 dated Oct. 6, 2015. | 
| Official Communication for European Patent Application No. 15188106.7 dated Feb. 3, 2016. | 
| Official Communication for European Patent Application No. 15190307.7 dated Feb. 19, 2016. | 
| Official Communication for Great Britain Patent Application No. 1404479.6 dated Aug. 12, 2014. | 
| Official Communication for Great Britain Patent Application No. 1404479.6 dated Jul. 9, 2015. | 
| Official Communication for Great Britain Patent Application No. 1404486.1 dated Aug. 27, 2014. | 
| Official Communication for Great Britain Patent Application No. 1404489.5 dated Aug. 27, 2014. | 
| Official Communication for Great Britain Patent Application No. 1404499.4 dated Aug. 20, 2014. | 
| Official Communication for Great Britain Patent Application No. 1413935.6 dated Dec. 21, 2015. | 
| Official Communication for Great Britain Patent Application No. 1413935.6 dated Jan. 27, 2015. | 
| Official Communication for Israel Patent Application No. 198253 dated Jan. 12, 2016. | 
| Official Communication for Israel Patent Application No. 198253 dated Nov. 24, 2014. | 
| Official Communication for Netherlands Patent Application No. 2011729 dated Aug. 13, 2015. | 
| Official Communication for Netherlands Patent Application No. 2012434 dated Jan. 8, 2016. | 
| Official Communication for Netherlands Patent Application No. 2012438 dated Sep. 21, 2015. | 
| Official Communication for Netherlands Patent Application No. 2013306 dated Apr. 24, 2015. | 
| Official Communication for New Zealand Patent Application No. 622389 dated Mar. 20, 2014. | 
| Official Communication for New Zealand Patent Application No. 622404 dated Mar. 20, 2014. | 
| Official Communication for New Zealand Patent Application No. 622414 dated Mar. 24, 2014. | 
| Official Communication for New Zealand Patent Application No. 622473 dated Jun. 19, 2014. | 
| Official Communication for New Zealand Patent Application No. 622484 dated Apr. 2, 2014. | 
| Official Communication for New Zealand Patent Application No. 622497 dated Jun. 19, 2014. | 
| Official Communication for New Zealand Patent Application No. 622497 dated Mar. 26, 2014. | 
| Official Communication for New Zealand Patent Application No. 622513 dated Apr. 3, 2014. | 
| Official Communication for New Zealand Patent Application No. 628161 dated Aug. 25, 2014. | 
| Online Tech Tips, "Clip2Net-Share files, folders and screenshots easily," , Apr. 2, 2008, pp. 5. | 
| Online Tech Tips, "Clip2Net-Share files, folders and screenshots easily," <http://www.online-tech-tips.com/free-software-downloads/share-files-foldersscreenshots/>, Apr. 2, 2008, pp. 5. | 
| O'Reilly.com, http://oreilly.com/digitalmedia/2006/01/01/mac-os-x-screenshot-secrets.html published Jan. 1, 2006 in 10 pages. | 
| Palantir, "Extracting and Transforming Data with Kite," Palantir Technologies, Inc., Copyright 2010, pp. 38. | 
| Palantir, "Kite Data-Integration Process Overview," Palantir Technologies, Inc., Copyright 2010, pp. 48. | 
| Palantir, "Kite Operations," Palantir Technologies, Inc., Copyright 2010, p. 1. | 
| Palantir, "Kite," https://docs.palantir.com/gotham/3.11.1.0/adminreference/datasources.11 printed Aug. 30, 2013 in 2 pages. | 
| Palantir, "The Repository Element," https://docs.palantir.com/gotham/3.11.1.0/dataguide/kite-config-file.04 printed Aug. 30, 2013 in 2 pages. | 
| Palantir, "Write a Kite Configuration File in Eclipse," Palantir Technologies, Inc., Copyright 2010, pp. 2. | 
| Palantir, https://docs.palantir.com/gotham/3.11.1.0/dataguide/baggage/KiteSchema.xsd printed Apr. 4, 2014 in 4 pages. | 
| Palermo, Christopher J., "Memorandum," [Disclosure relating to U.S. Appl. No. 13/916,447, filed Jun. 12, 2013, and related applications], Jan. 31, 2014 in 3 pages. | 
| Schroder, Stan, "15 Ways to Create Website Screenshots," , Aug. 24, 2007, pp. 2. | 
| Schroder, Stan, "15 Ways to Create Website Screenshots," <http://mashable.com/2007/08/24/web-screenshots/>, Aug. 24, 2007, pp. 2. | 
| Snaglt, "Snaglt 8.1.0 Print Out 2," Software release date Jun. 15, 2006, pp. 1-3. | 
| Snaglt, "Snaglt 8.1.0 Print Out," Software release date Jun. 15, 2006, pp. 6. | 
| Snaglt, "Snaglt Online Help Guide," , TechSmith Corp., Version 8.1, printed Feb. 7, 2007, pp. 284. | 
| Snaglt, "Snaglt Online Help Guide," <http://download.techsmith.com/snagit/docs/onlinehelp/enu/snagit-help.pdf>, TechSmith Corp., Version 8.1, printed Feb. 7, 2007, pp. 284. | 
| Symantec Corporation, "E-Security Begins with Sound Security Policies," Announcement Symantec, Jun. 14, 2001. | 
| U.S. Appl. No. 12/556,321, filed Sep. 9, 2009, Final Office Action, Feb. 25, 2016. | 
| U.S. Appl. No. 12/556,321, filed Sep. 9, 2009, Office Action, Jul. 7, 2015. | 
| U.S. Appl. No. 13/669,274, filed Nov. 5, 2012, Advisory Action Aug. 26, 2015. | 
| U.S. Appl. No. 13/669,274, filed Nov. 5, 2012, Final Office Action, May 6, 2015. | 
| U.S. Appl. No. 13/827,491, filed Mar. 14, 2013, Final Office Action, Jun. 22, 2015. | 
| U.S. Appl. No. 13/827,491, filed Mar. 14, 2013, Office Action, Oct. 9, 2015. | 
| U.S. Appl. No. 14/025,653, filed Sep. 12, 2013, Interview, Mar. 3, 2016. | 
| U.S. Appl. No. 14/025,653, filed Sep. 12, 2013, Office Action Interview, Oct. 6, 2015. | 
| U.S. Appl. No. 14/044,800, filed Oct. 2, 2013, Notice of Allowance, Sep. 2, 2014. | 
| U.S. Appl. No. 14/134,558, filed Dec. 19, 2013, Office Action, Oct. 7, 2015. | 
| U.S. Appl. No. 14/148,568, filed Jan. 6, 2014, Final Office Action, Oct. 22, 2014. | 
| U.S. Appl. No. 14/148,568, filed Jan. 6, 2014, Notice of Allowance, Aug. 26, 2015. | 
| U.S. Appl. No. 14/148,568, filed Jan. 6, 2014, Office Action, Mar. 26, 2015. | 
| U.S. Appl. No. 14/222,364, filed Mar. 21, 2014, Office Action, Dec. 9, 2015. | 
| U.S. Appl. No. 14/265,637, filed Apr. 30, 2014, Notice of Allowance, Feb. 13, 2015. | 
| U.S. Appl. No. 14/508,696, filed Oct. 7, 2014, Notice of Allowance, Jul. 27, 2015. | 
| U.S. Appl. No. 14/508,696, filed Oct. 7, 2014, Office Action, Mar. 2, 2015. | 
| U.S. Appl. No. 14/526,066, filed Oct. 28, 2014, Office Action, Jan. 21, 2016. | 
| U.S. Appl. No. 14/533,433, filed Nov. 5, 2014, Notice of Allowance, Sep. 1, 2015. | 
| U.S. Appl. No. 14/552,336, filed Nov. 24, 2014, First Office Action Interview, Jul. 20, 2015. | 
| U.S. Appl. No. 14/552,336, filed Nov. 24, 2014, Notice of Allowance, Nov. 3, 2015. | 
| U.S. Appl. No. 14/571,098, filed Dec. 15, 2014, First Office Action Interview, Aug. 24, 2015. | 
| U.S. Appl. No. 14/571,098, filed Dec. 15, 2014, First Office Action Interview, Mar. 11, 2015. | 
| U.S. Appl. No. 14/571,098, filed Dec. 15, 2014, First Office Action Interview, Nov. 10, 2015. | 
| U.S. Appl. No. 14/631,633, filed Feb. 25, 2015, First Office, Feb. 3, 2016. | 
| U.S. Appl. No. 14/715,834, filed May 19, 2015, First Office Action Interview, Feb. 19, 2016. | 
| U.S. Appl. No. 14/741,256, filed Jun. 16, 2015, Office Action, Feb. 9, 2016. | 
| U.S. Appl. No. 14/800,447, filed Jul. 15, 2012, First Office Action Interview, Dec. 10, 2010. | 
| U.S. Appl. No. 14/841,338, filed Aug. 31, 2015, Office Action, Feb. 18, 2016. | 
| U.S. Appl. No. 14/842,734, filed Sep. 1, 2015, First Office Action Interview, Nov. 19, 2015. | 
| U.S. Appl. No. 14/871,465, filed Sep. 30, 2015, First Office Action Interview, Feb. 9, 2016. | 
| U.S. Appl. No. 14/883,498, filed Oct. 14, 2015, First Office Action Interview, Dec. 24, 2015. | 
| Wang et al., "Research on a Clustering Data De-Duplication Mechanism Based on Bloom Filter," IEEE 2010, 5 pages. | 
| Warren, Christina, "TUAW Faceoff: Screenshot apps on the firing line," <http://www.tuaw.com/2008/05/05/tuaw-faceoff-screenshot-apps-on-the-firing-lineh, May 5, 2008, pp. 11. | 
| Wollrath et al., "A Distributed Object Model for the Java System," Conference on Object-Oriented Technologies and Systems, Jun. 17-21, 1996, pp. 219-231. | 
Cited By (4)
| Publication number | Priority date | Publication date | Assignee | Title | 
|---|---|---|---|---|
| US10872067B2 (en) | 2006-11-20 | 2020-12-22 | Palantir Technologies, Inc. | Creating data in a data store using a dynamic ontology | 
| US10803106B1 (en) | 2015-02-24 | 2020-10-13 | Palantir Technologies Inc. | System with methodology for dynamic modular ontology | 
| US10248722B2 (en) | 2016-02-22 | 2019-04-02 | Palantir Technologies Inc. | Multi-language support for dynamic ontology | 
| US10909159B2 (en) | 2016-02-22 | 2021-02-02 | Palantir Technologies Inc. | Multi-language support for dynamic ontology | 
Also Published As
Similar Documents
| Publication | Publication Date | Title | 
|---|---|---|
| US12386803B2 (en) | Creating data in a data store using a dynamic ontology | |
| US11436126B2 (en) | Customizable enterprise automation test framework | |
| US8683324B2 (en) | Dynamic generation of target files from template files and tracking of the processing of target files | |
| US20030018661A1 (en) | XML smart mapping system and method | |
| US20130304769A1 (en) | Document Merge Based on Knowledge of Document Schema | |
| CA2680306A1 (en) | Identification of concepts in software | |
| US20110078201A1 (en) | Ragged and unbalanced hierarchy management and visualization | |
| US11570230B1 (en) | System and method for creating a protocol-compliant uniform resource locator | |
| CN112650526B (en) | Method, device, electronic equipment and medium for detecting version consistency | |
| US7818328B2 (en) | API for obtaining unambiguous representation of objects in a relational database | |
| CN119048294A (en) | Contract numbering method and device, storage medium and terminal equipment | |
| US8200613B1 (en) | Approach for performing metadata reconciliation | |
| CN121833038A (en) | Topological relation diagram generation method and service identification device | 
Legal Events
| Date | Code | Title | Description | 
|---|---|---|---|
| STCF | Information on status: patent grant | Free format text: PATENTED CASE | |
| AS | Assignment | Owner name: ROYAL BANK OF CANADA, AS ADMINISTRATIVE AGENT, CANADA Free format text: SECURITY INTEREST;ASSIGNOR:PALANTIR TECHNOLOGIES INC.;REEL/FRAME:051709/0471 Effective date: 20200127 Owner name: MORGAN STANLEY SENIOR FUNDING, INC., AS ADMINISTRATIVE AGENT, NEW YORK Free format text: SECURITY INTEREST;ASSIGNOR:PALANTIR TECHNOLOGIES INC.;REEL/FRAME:051713/0149 Effective date: 20200127 | |
| AS | Assignment | Owner name: PALANTIR TECHNOLOGIES INC., CALIFORNIA Free format text: RELEASE BY SECURED PARTY;ASSIGNOR:ROYAL BANK OF CANADA;REEL/FRAME:052856/0382 Effective date: 20200604 Owner name: MORGAN STANLEY SENIOR FUNDING, INC., NEW YORK Free format text: SECURITY INTEREST;ASSIGNOR:PALANTIR TECHNOLOGIES INC.;REEL/FRAME:052856/0817 Effective date: 20200604 | |
| MAFP | Maintenance fee payment | Free format text: PAYMENT OF MAINTENANCE FEE, 4TH YEAR, LARGE ENTITY (ORIGINAL EVENT CODE: M1551); ENTITY STATUS OF PATENT OWNER: LARGE ENTITY Year of fee payment: 4 | |
| AS | Assignment | Owner name: PALANTIR TECHNOLOGIES INC., CALIFORNIA Free format text: CORRECTIVE ASSIGNMENT TO CORRECT THE ERRONEOUSLY LISTED PATENT BY REMOVING APPLICATION NO. 16/832267 FROM THE RELEASE OF SECURITY INTEREST PREVIOUSLY RECORDED ON REEL 052856 FRAME 0382. ASSIGNOR(S) HEREBY CONFIRMS THE RELEASE OF SECURITY INTEREST;ASSIGNOR:ROYAL BANK OF CANADA;REEL/FRAME:057335/0753 Effective date: 20200604 | |
| AS | Assignment | Owner name: WELLS FARGO BANK, N.A., NORTH CAROLINA Free format text: ASSIGNMENT OF INTELLECTUAL PROPERTY SECURITY AGREEMENTS;ASSIGNOR:MORGAN STANLEY SENIOR FUNDING, INC.;REEL/FRAME:060572/0640 Effective date: 20220701 Owner name: WELLS FARGO BANK, N.A., NORTH CAROLINA Free format text: SECURITY INTEREST;ASSIGNOR:PALANTIR TECHNOLOGIES INC.;REEL/FRAME:060572/0506 Effective date: 20220701 | |
| MAFP | Maintenance fee payment | Free format text: PAYMENT OF MAINTENANCE FEE, 8TH YEAR, LARGE ENTITY (ORIGINAL EVENT CODE: M1552); ENTITY STATUS OF PATENT OWNER: LARGE ENTITY Year of fee payment: 8 |
