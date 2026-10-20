"""WPF layouts (XAML) for the "Model Prep" button: the main window and the Decisions dialog.

Plain strings so they can be checked outside Revit; the button loads them with
``forms.WPFWindow(xaml, literal_string=True)``.  IronPython 2.7 + CPython 3.
"""

COLOURS = {"OK  ": "#1B7F2A", "WARN": "#B26A00", "FAIL": "#C62828", "": "#333333", "HEAD": "#000000"}

_NS = ('xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
       'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"')

_WINDOW = '''<Window {ns}
        Title="Model Prep by Netbuild" Width="1120" Height="880" MinWidth="900" MinHeight="600"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" FontSize="12" ShowInTaskbar="False">
  <DockPanel Margin="10">
    <StackPanel DockPanel.Dock="Top">
      <TextBlock x:Name="model_tb" FontWeight="Bold" FontSize="13"/>
      <Grid Margin="0,8,0,0">
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="120"/>
          <ColumnDefinition Width="*"/>
          <ColumnDefinition Width="Auto"/>
        </Grid.ColumnDefinitions>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <TextBlock Grid.Row="0" Grid.Column="0" Text="Host building" VerticalAlignment="Center" Margin="0,3"/>
        <StackPanel Grid.Row="0" Grid.Column="1" Orientation="Horizontal" Margin="0,3">
          <TextBox x:Name="building_tb" Width="80" FontWeight="Bold"/>
          <TextBlock x:Name="host_tb" Foreground="#555555" VerticalAlignment="Center" Margin="10,0,0,0"/>
        </StackPanel>
        <TextBlock Grid.Row="1" Grid.Column="0" Text="Workset register" VerticalAlignment="Center" Margin="0,3"/>
        <TextBox x:Name="register_tb" Grid.Row="1" Grid.Column="1" Margin="0,3"/>
        <Button x:Name="browse_btn" Grid.Row="1" Grid.Column="2" Content="Browse..." Padding="8,1" Margin="6,3,0,3"/>
        <TextBlock Grid.Row="2" Grid.Column="0" Text="Tab" VerticalAlignment="Center" Margin="0,3"/>
        <StackPanel Grid.Row="2" Grid.Column="1" Orientation="Horizontal" Margin="0,3">
          <ComboBox x:Name="sheet_cb" Width="220"/>
          <TextBlock x:Name="register_info_tb" Foreground="#555555" VerticalAlignment="Center" Margin="10,0,0,0"/>
        </StackPanel>
        <Button x:Name="reload_btn" Grid.Row="2" Grid.Column="2" Content="Read again" Padding="8,1" Margin="6,3,0,3"/>
      </Grid>
    </StackPanel>
    <GroupBox DockPanel.Dock="Top" Margin="0,8,0,0" Header="Steps">
      <StackPanel Margin="4">
        <CheckBox x:Name="step1_cb" IsChecked="True" Margin="0,2"
                  Content="01  Discipline links -- building-specific only: report OK / WRONG SCOPE / MISSING, remove wrong-scope links"/>
        <CheckBox x:Name="step2_cb" IsChecked="True" Margin="0,2"
                  Content="02  Worksets -- create the register's missing worksets (none deleted), rename the pairs you tick"/>
        <CheckBox x:Name="step3_cb" IsChecked="True" Margin="0,2"
                  Content="03  Link worksets -- every link type AND instance onto its Link-* workset"/>
      </StackPanel>
    </GroupBox>
    <WrapPanel DockPanel.Dock="Top" Margin="0,8,0,0">
      <Button x:Name="check_btn" Content="1. Check (changes nothing)" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="decide_btn" Content="Decisions..." Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="apply_btn" Content="2. Apply" Padding="10,3" Margin="0,0,20,0" FontWeight="Bold"/>
      <Button x:Name="paths_btn" Content="Copy missing-link paths" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="rules_btn" Content="Rules..." Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="logs_btn" Content="Open logs folder" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="about_btn" Content="About" Padding="10,3" Margin="0,0,6,0"/>
      <Button x:Name="close_btn" Content="Close" Padding="10,3"/>
    </WrapPanel>
    <TextBlock x:Name="status_tb" DockPanel.Dock="Top" Foreground="#555555" Margin="0,6,0,0" TextWrapping="Wrap"/>
    <ListBox x:Name="report_lb" Margin="0,6,0,0" FontFamily="Consolas" FontSize="11"
             ScrollViewer.HorizontalScrollBarVisibility="Auto"/>
  </DockPanel>
</Window>'''

_DECISIONS = '''<Window {ns}
        Title="Model Prep -- decisions" Width="980" Height="720" MinWidth="700" MinHeight="400"
        WindowStartupLocation="CenterOwner" FontFamily="Segoe UI" FontSize="12" ShowInTaskbar="False">
  <DockPanel Margin="12">
    <StackPanel DockPanel.Dock="Bottom" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,10,0,0">
      <CheckBox x:Name="remember_cb" VerticalAlignment="Center" Margin="0,0,20,0"
                Content="Remember my workset answers as rules for these file names"/>
      <Button x:Name="ok_btn" Content="OK -- check again" Width="130" Margin="0,0,6,0" IsDefault="True"/>
      <Button x:Name="cancel_btn" Content="Cancel" Width="80" IsCancel="True"/>
    </StackPanel>
    <ScrollViewer VerticalScrollBarVisibility="Auto">
      <StackPanel>
        <GroupBox Header="Step 01 -- links to remove on Apply (a Tower / Site-Wide / other building's file, not this building's own)"
                  Margin="0,0,0,8" Visibility="{rm_vis}">
          <StackPanel Margin="4">{rm_rows}
          </StackPanel>
        </GroupBox>
        <GroupBox Header="Step 02 -- the same workset spelled two ways? Tick to rename the model's workset to the register's name"
                  Margin="0,0,0,8" Visibility="{pair_vis}">
          <StackPanel Margin="4">
            <TextBlock Foreground="#555555" TextWrapping="Wrap" Margin="0,0,0,4"
                       Text="The register's name always wins. The model's workset is renamed, so every element stays on it; nothing is moved or deleted. Leave a pair unticked when the two are really different worksets."/>{pair_rows}
          </StackPanel>
        </GroupBox>
        <GroupBox Header="Step 03 -- links with no confident rule: pick the workset (or leave the link where it is)"
                  Visibility="{ask_vis}">
          <Grid Margin="4">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="300"/>
            </Grid.ColumnDefinitions>
            <Grid.RowDefinitions>{ask_rowdefs}
            </Grid.RowDefinitions>{ask_rows}
          </Grid>
        </GroupBox>
        <TextBlock x:Name="none_tb" Visibility="{none_vis}" Margin="4"
                   Text="Nothing to decide: no wrong-scope links, no look-alike worksets, every link has a rule."/>
      </StackPanel>
    </ScrollViewer>
  </DockPanel>
</Window>'''

_RM = '''
            <CheckBox x:Name="rm_{i}" Margin="0,2"/>'''
_PAIR = '''
            <CheckBox x:Name="pair_{i}" Margin="0,2"/>'''
_ASK = '''
            <TextBlock x:Name="ask_name_{i}" Grid.Row="{i}" Grid.Column="0" TextWrapping="Wrap" Margin="0,4,8,4"
                       VerticalAlignment="Center"/>
            <ComboBox x:Name="ask_ws_{i}" Grid.Row="{i}" Grid.Column="1" Margin="0,4" VerticalAlignment="Center"/>'''

LEAVE = "(leave where it is)"


def _vis(n):
    return "Visible" if n else "Collapsed"


def window_xaml():
    return _WINDOW.format(ns=_NS)


def decisions_xaml(n_remove, n_pairs, n_ask):
    return _DECISIONS.format(
        ns=_NS, rm_vis=_vis(n_remove), pair_vis=_vis(n_pairs), ask_vis=_vis(n_ask),
        none_vis=_vis(not (n_remove or n_pairs or n_ask)),
        rm_rows="".join(_RM.format(i=i) for i in range(n_remove)),
        pair_rows="".join(_PAIR.format(i=i) for i in range(n_pairs)),
        ask_rowdefs="".join('\n              <RowDefinition Height="Auto"/>' for _ in range(n_ask)),
        ask_rows="".join(_ASK.format(i=i) for i in range(n_ask)))
