# The grammar this engine parses

Written the way the parser reads it: loosest precedence first. Anything not
listed here is not supported — the parser says so rather than ignoring it.

```
statement  := query | insert | update | delete

query      := select { UNION [ALL] select }
              [ ORDER BY order { ',' order } ]
              [ LIMIT integer ] [ OFFSET integer ]
select     := SELECT [DISTINCT] items [ FROM table { join } ]
              [ WHERE expr ]
              [ GROUP BY expr { ',' expr } [ HAVING expr ] ]

insert     := INSERT INTO name [ '(' name { ',' name } ')' ]
              ( VALUES row { ',' row } | query )
row        := '(' expr { ',' expr } ')'
update     := UPDATE name SET name '=' expr { ',' name '=' expr } [ WHERE expr ]
delete     := DELETE FROM name [ WHERE expr ]

items      := item { ',' item }
item       := '*' | name '.' '*' | expr [ [AS] alias ]

table      := name [ [AS] alias ]
join       := [ INNER | LEFT ] JOIN table ON expr
order      := expr [ ASC | DESC ]

expr       := or
or         := and { OR and }
and        := not { AND not }
not        := NOT not | comparison
comparison := sum [ ( '=' | '<>' | '!=' | '<' | '<=' | '>' | '>=' ) sum
                  | IS [NOT] NULL
                  | [NOT] IN '(' expr { ',' expr } ')'
                  | [NOT] LIKE sum
                  | [NOT] BETWEEN sum AND sum ]
sum        := product { ( '+' | '-' ) product }
product    := unary { ( '*' | '/' | '%' ) unary }
unary      := '-' unary | primary
primary    := number | string | NULL | TRUE | FALSE
            | aggregate | function | case | column | '(' expr ')'
function   := ( UPPER | LOWER | LENGTH | TRIM | ABS ) '(' expr ')'
            | ROUND '(' expr [ ',' expr ] ')'
            | COALESCE '(' expr { ',' expr } ')'
            | NULLIF '(' expr ',' expr ')'
case       := CASE [ expr ] WHEN expr THEN expr { WHEN expr THEN expr }
              [ ELSE expr ] END

aggregate  := ( COUNT '(' '*' ')' )
            | ( COUNT | SUM | AVG | MIN | MAX ) '(' [DISTINCT] expr ')'
column     := name [ '.' name ]
```

## Notes

- **Keywords, table names and column names are all case-insensitive.** `SELECT`
  and `select` are the same word, `Orders` and `orders` the same table, and
  `NAME` and `name` the same column (the result column is labelled as you typed it).
- **Strings use single quotes**, and `''` inside one is a literal quote.
- **`--` starts a comment** that runs to the end of the line.
- **`LIMIT` and `OFFSET` take whole numbers only.** `LIMIT 2.5` is an error, not
  a silent truncation.
- **`HAVING` requires `GROUP BY`.** Without one there is no group to filter.
- **ORDER BY after a UNION** names an output column of the first `SELECT`, or its
  position (`ORDER BY 2`), and sorts the combined result.
- **`x NOT IN (1, NULL)`** is never true: `x = NULL` is unknown, so x might
  be in the list. `IN` is true on a match, unknown if any item is NULL, false
  otherwise.
- **Without `FROM`** a query evaluates once over a single empty row
  (`SELECT 1 + 1`); naming a column there is reported as a forgotten `FROM`.
- **`GROUP BY`** accepts, next to aggregates, any expression built only from
  grouped expressions and constants (`UPPER(city)` grouped by `city`, a literal label).
- **`CASE x WHEN NULL`** never matches: it compares with `=`, and `NULL = NULL`
  is unknown. Use `CASE WHEN x IS NULL THEN …` instead.
- **Writes change memory, not files.** `.save` in the shell or `--save` on the
  command line writes the changed tables back to their CSVs.
