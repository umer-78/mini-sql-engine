# The grammar this engine parses

Written the way the parser reads it: loosest precedence first. Anything not
listed here is not supported — the parser says so rather than ignoring it.

```
statement  := query | insert | update | delete

query      := select { UNION [ALL] select }
              [ ORDER BY order { ',' order } ]
              [ LIMIT integer ] [ OFFSET integer ]
select     := SELECT [DISTINCT] items FROM table { join }
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
                  | [NOT] LIKE sum ]
sum        := product { ( '+' | '-' ) product }
product    := unary { ( '*' | '/' | '%' ) unary }
unary      := '-' unary | primary
primary    := number | string | NULL | TRUE | FALSE
            | aggregate | case | column | '(' expr ')'
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
- **`CASE x WHEN NULL`** never matches: it compares with `=`, and `NULL = NULL`
  is unknown. Use `CASE WHEN x IS NULL THEN …` instead.
- **Writes change memory, not files.** `.save` in the shell or `--save` on the
  command line writes the changed tables back to their CSVs.
