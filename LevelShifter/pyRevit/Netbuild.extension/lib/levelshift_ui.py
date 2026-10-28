"""WPF layouts (XAML) for the "Level Shift" button: the main window and the Define-new-level dialog.

Plain strings so they can be checked outside Revit; the button loads them with
``forms.WPFWindow(xaml, literal_string=True)``.  IronPython 2.7 + CPython 3.
"""

CURRENT_BG = "#FFF3BF"      # the read-only "current elevation" field
COLOURS = {"OK  ": "#1B7F2A", "WARN": "#B26A00", "FAIL": "#C62828", "": "#333333"}
UP, DOWN, NONE = "#1B7F2A", "#C62828", "#555555"

_NS = ('xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
       'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"')

_ROW = '''
        <TextBlock Grid.Row="{r}" Grid.Column="0" Text="{n}" VerticalAlignment="Center" Margin="4,3"/>
        <ComboBox x:Name="lvl_{i}" Grid.Row="{r}" Grid.Column="1" Margin="4,3"/>
        <TextBox x:Name="cur_{i}" Grid.Row="{r}" Grid.Column="2" Margin="4,3" IsReadOnly="True" Focusable="False"
                 Background="{bg}" TextAlignment="Right" BorderBrush="#B8A000"/>
        <TextBox x:Name="new_{i}" Grid.Row="{r}" Grid.Column="3" Margin="4,3" TextAlignment="Right"/>
        <TextBox x:Name="by_{i}" Grid.Row="{r}" Grid.Column="4" Margin="4,3" TextAlignment="Right"/>
        <TextBlock x:Name="dir_{i}" Grid.Row="{r}" Grid.Column="5" Margin="4,3" VerticalAlignment="Center"
                   FontWeight="Bold"/>
        <Button x:Name="def_{i}" Grid.Row="{r}" Grid.Column="6" Margin="4,3" Padding="8,1"
                Content="Define new level..."/>'''

_WINDOW = '''<Window {ns}
        Title="Level Shift by Netbuild" Width="1010" Height="880" MinWidth="900" MinHeight="620"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" FontSize="12" ShowInTaskbar="False">
  <DockPanel Margin="10">
    <StackPanel DockPanel.Dock="Top">
      <TextBlock x:Name="model_tb" FontWeight="Bold" FontSize="13"/>
      <StackPanel Orientation="Horizontal" Margin="0,6,0,0">
        <TextBlock Text="Units" VerticalAlignment="Center" Margin="0,0,8,0"/>
        <RadioButton x:Name="mm_rb" Content="mm" GroupName="units" VerticalAlignment="Center" Margin="0,0,10,0"/>
        <RadioButton x:Name="m_rb" Content="m" GroupName="units" VerticalAlignment="Center"/>
        <TextBlock x:Name="base_tb" Foreground="#555555" VerticalAlignment="Center" Margin="20,0,0,0"/>
      </StackPanel>
    </StackPanel>
    <GroupBox DockPanel.Dock="Top" Margin="0,8,0,0"
              Header="Levels to move (up to {count}) -- every element hosted to them keeps its X, Y, Z">
      <Grid x:Name="rows_grid" Margin="4">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="28"/>
          <ColumnDefinition Width="230"/>
          <ColumnDefinition Width="140"/>
          <ColumnDefinition Width="120"/>
          <ColumnDefinition Width="130"/>
          <ColumnDefinition Width="56"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <Grid.RowDefinitions>{rowdefs}
        </Grid.RowDefinitions>
        <TextBlock Grid.Row="0" Grid.Column="0" Text="#" FontWeight="Bold" Margin="4,3"/>
        <TextBlock Grid.Row="0" Grid.Column="1" Text="Level" FontWeight="Bold" Margin="4,3"/>
        <TextBlock Grid.Row="0" Grid.Column="2" Text="Current elevation" FontWeight="Bold" Margin="4,3"/>
        <TextBlock Grid.Row="0" Grid.Column="3" Text="New elevation" FontWeight="Bold" Margin="4,3"/>
        <TextBlock Grid.Row="0" Grid.Column="4" Text="Move (+up / -down)" FontWeight="Bold" Margin="4,3"/>{rows}
      </Grid>
    </GroupBox>
    <WrapPanel DockPanel.Dock="Top" Margin="0,6,0,0">
      <Button x:Name="same_btn" Content="Same move for every row..." Padding="8,2" Margin="0,0,6,0"/>
      <Button x:Name="clear_btn" Content="Clear values" Padding="8,2" Margin="0,0,6,0"/>
      <Button x:Name="clear_rows_btn" Content="Clear rows" Padding="8,2" Margin="0,0,10,0"/>
      <TextBlock Foreground="#555555" VerticalAlignment="Center"
                 Text="type a new elevation OR a move; values may carry mm / m (3500, +300, -150, 10.5m)"/>
    </WrapPanel>
    <WrapPanel DockPanel.Dock="Top" Margin="0,8,0,0">
      <TextBlock Text="Tolerance (mm)" VerticalAlignment="Center" Margin="0,0,6,0"/>
      <TextBox x:Name="tol_tb" Width="50" TextAlignment="Right" Margin="0,0,14,0"/>
      <CheckBox x:Name="fallback_cb" VerticalAlignment="Center" Margin="0,0,14,0"
                Content="Move back elements that have no offset parameter"/>
      <CheckBox x:Name="rollback_cb" VerticalAlignment="Center" Margin="0,0,14,0" Content="Undo all if anything moves"/>
      <CheckBox x:Name="groups_cb" VerticalAlignment="Center"
                Content="Groups: ungroup, fix and regroup when members cannot be kept in place"/>
    </WrapPanel>
    <WrapPanel DockPanel.Dock="Top" Margin="0,8,0,0">
      <Button x:Name="check_btn" Content="1. Check (plan only)" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="trial_btn" Content="2. Trial run (rolls back)" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="apply_btn" Content="3. Apply" Padding="10,3" Margin="0,0,20,0" FontWeight="Bold"/>
      <Button x:Name="logs_btn" Content="Open logs folder" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="about_btn" Content="About" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="close_btn" Content="Close" Padding="10,3"/>
    </WrapPanel>
    <TextBlock x:Name="status_tb" DockPanel.Dock="Top" Foreground="#555555" Margin="0,6,0,0" TextWrapping="Wrap"/>
    <ListBox x:Name="report_lb" Margin="0,6,0,0" FontFamily="Consolas" FontSize="11"
             ScrollViewer.HorizontalScrollBarVisibility="Auto"/>
  </DockPanel>
</Window>'''

_DEFINE = '''<Window {ns}
        Title="Define new level" SizeToContent="WidthAndHeight" ResizeMode="NoResize"
        WindowStartupLocation="CenterOwner" FontFamily="Segoe UI" FontSize="12" ShowInTaskbar="False">
  <StackPanel Margin="14">
    <Grid>
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="170"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>
      <TextBlock Grid.Row="0" Grid.Column="0" Text="Level" Margin="0,3"/>
      <TextBlock x:Name="name_tb" Grid.Row="0" Grid.Column="1" FontWeight="Bold" Margin="0,3"/>
      <TextBlock Grid.Row="1" Grid.Column="0" Text="Current elevation" VerticalAlignment="Center" Margin="0,3"/>
      <TextBox x:Name="cur_tb" Grid.Row="1" Grid.Column="1" Width="140" HorizontalAlignment="Left" Margin="0,3"
               IsReadOnly="True" Focusable="False" Background="{bg}" TextAlignment="Right" BorderBrush="#B8A000"/>
    </Grid>
    <Separator Margin="0,8"/>
    <StackPanel Orientation="Horizontal" Margin="0,3">
      <RadioButton x:Name="to_rb" GroupName="how" Width="170" VerticalAlignment="Center"
                   Content="New elevation ({units})"/>
      <TextBox x:Name="abs_tb" Width="140" TextAlignment="Right"/>
    </StackPanel>
    <StackPanel Orientation="Horizontal" Margin="0,3">
      <RadioButton x:Name="by_rb" GroupName="how" Width="170" VerticalAlignment="Center"
                   Content="Move by ({units})"/>
      <TextBox x:Name="amount_tb" Width="90" TextAlignment="Right" Margin="0,0,10,0"/>
      <RadioButton x:Name="up_rb" GroupName="dir" Content="Up (+)" VerticalAlignment="Center" Margin="0,0,10,0"/>
      <RadioButton x:Name="down_rb" GroupName="dir" Content="Down (-)" VerticalAlignment="Center"/>
    </StackPanel>
    <TextBlock x:Name="result_tb" Margin="0,10,0,0" FontWeight="Bold"/>
    <TextBlock Foreground="#555555" Margin="0,6,0,0" TextWrapping="Wrap" MaxWidth="420"
               Text="The level moves; every element hosted to it keeps its X, Y, Z (its offset from the level changes by the opposite amount)."/>
    <StackPanel Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,12,0,0">
      <Button x:Name="ok_btn" Content="OK" Width="80" Margin="0,0,6,0" IsDefault="True"/>
      <Button x:Name="cancel_btn" Content="Cancel" Width="80" IsCancel="True"/>
    </StackPanel>
  </StackPanel>
</Window>'''


_ABOUT = '''<Window {ns}
        Title="About {product}" Width="760" Height="720" MinWidth="560" MinHeight="480"
        WindowStartupLocation="CenterOwner" FontFamily="Segoe UI" FontSize="12" ShowInTaskbar="False">
  <DockPanel Margin="16">
    <StackPanel DockPanel.Dock="Top">
      <TextBlock x:Name="product_tb" FontSize="20" FontWeight="Bold"/>
      <TextBlock x:Name="version_tb" Foreground="#555555" Margin="0,2,0,0"/>
      <TextBlock x:Name="desc_tb" TextWrapping="Wrap" Margin="0,10,0,0"/>
    </StackPanel>
    <StackPanel DockPanel.Dock="Bottom" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,10,0,0">
      <Button x:Name="copy_btn" Content="Copy product info" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="licence_btn" Content="Licence" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="web_btn" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="close_btn" Content="Close" Padding="10,3" IsCancel="True" IsDefault="True"/>
    </StackPanel>
    <TextBlock x:Name="licence_line_tb" DockPanel.Dock="Bottom" TextWrapping="Wrap" Margin="0,8,0,0"/>
    <Grid Margin="0,10,0,0">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <GroupBox Grid.Row="0" Grid.Column="0" Header="Features" Margin="0,0,6,6">
        <TextBlock x:Name="features_tb" TextWrapping="Wrap" Margin="4"/>
      </GroupBox>
      <GroupBox Grid.Row="0" Grid.Column="1" Header="Requirements" Margin="0,0,0,6">
        <TextBlock x:Name="req_tb" TextWrapping="Wrap" Margin="4"/>
      </GroupBox>
    </Grid>
  </DockPanel>
</Window>'''


_LICENCE = '''<Window {ns}
        Title="Licence -- {product}" Width="760" Height="720" MinWidth="560" MinHeight="480"
        WindowStartupLocation="CenterOwner" FontFamily="Segoe UI" FontSize="12" ShowInTaskbar="False">
  <DockPanel Margin="16">
    <StackPanel DockPanel.Dock="Top">
      <TextBlock Text="Licence" FontSize="20" FontWeight="Bold"/>
      <TextBlock x:Name="product_tb" Margin="0,2,0,0"/>
      <TextBlock x:Name="kind_tb" FontWeight="Bold" Margin="0,8,0,0"/>
      <TextBlock x:Name="owner_tb" Foreground="#555555"/>
      <TextBlock x:Name="key_tb" Margin="0,2,0,8"/>
    </StackPanel>
    <StackPanel DockPanel.Dock="Bottom" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,10,0,0">
      <Button x:Name="copy_btn" Content="Copy licence" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="web_btn" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="close_btn" Content="Close" Padding="10,3" IsCancel="True" IsDefault="True"/>
    </StackPanel>
    <GroupBox x:Name="license_gb">
      <TextBox x:Name="license_tb" IsReadOnly="True" TextWrapping="Wrap" FontFamily="Consolas" FontSize="11"
               VerticalScrollBarVisibility="Auto" BorderThickness="0"/>
    </GroupBox>
  </DockPanel>
</Window>'''


def about_xaml(product):
    return _ABOUT.format(ns=_NS, product=product)


def licence_xaml(product):
    return _LICENCE.format(ns=_NS, product=product)


def window_xaml(count):
    rowdefs = "".join('\n          <RowDefinition Height="Auto"/>' for _ in range(count + 1))
    rows = "".join(_ROW.format(r=i + 1, n=i + 1, i=i, bg=CURRENT_BG) for i in range(count))
    return _WINDOW.format(ns=_NS, count=count, rowdefs=rowdefs, rows=rows)


def define_xaml(units):
    return _DEFINE.format(ns=_NS, bg=CURRENT_BG, units=units)


def report_lines(checks, lines):
    """[(colour, text)] for the report list: the checks (coloured by result), then the detail lines."""
    out = [(COLOURS[c.mark], str(c)) for c in checks]
    return out + [(COLOURS[""], l) for l in lines]
